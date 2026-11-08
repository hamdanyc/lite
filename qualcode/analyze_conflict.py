import argparse
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    from dotenv import load_dotenv
    from groq import APIError, Groq, RateLimitError
except ImportError as exc:
    sys.stderr.write(
        f"Missing dependency: {exc.name}. "
        "Run: pip install -r requirements.txt\n"
    )
    raise SystemExit(1)

MODEL = "qwen/qwen3.8-27b"
MAX_ARTICLE_CHARS = 20000
API_SLEEP_SECONDS = 0.5
MAX_RETRIES = 3
SUGGESTED_MAX_FILES = 25
COMMON_ARTICLE_DIRS = [
    "Articles",
    "articles",
    "resource/Articles",
    "resource/articles",
    "data/Articles",
    "data/articles",
    "input/Articles",
    "input/articles",
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_api_key() -> str:
    load_dotenv()
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise OSError(
            "GROQ_API_KEY is missing. Copy .env.example to .env and set the key."
        )
    return key


def extract_codes(codebook_path: Path) -> list[dict]:
    resolved = codebook_path.resolve()
    if not codebook_path.exists():
        raise FileNotFoundError(f"Codebook not found: {resolved}")
    root = ET.parse(codebook_path).getroot()
    codes: list[dict] = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "Code":
            continue
        name = (el.get("name") or el.get("Name") or "").strip()
        desc = ""
        for child in el:
            if child.tag.split("}")[-1] in ("Description", "Text", "Comment") and child.text:
                desc = child.text.strip()
                break
        if not desc and el.text:
            desc = el.text.strip()
        if name:
            codes.append({"factor": name, "description": desc or name})
    if not codes:
        raise ValueError(f"No <Code> elements found in {resolved}")
    return codes


def extract_text(html_path: Path) -> str:
    raw = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def call_llm(client: Groq, messages: list[dict], json_mode: bool = True) -> str:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            kwargs = {"model": MODEL, "messages": messages, "temperature": 0}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except RateLimitError as e:
            last_err = e
            time.sleep(2 ** attempt)
        except APIError as e:
            last_err = e
            logging.getLogger(__name__).warning(
                "Groq API error (attempt %d): %s", attempt + 1, e
            )
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_err}")


def parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


def get_semantic_phrases(client: Groq, factor: str, description: str) -> list[str]:
    prompt = (
        "You are analyzing ethnic conflict. Given a factor from a conflict-analysis "
        "codebook, produce multi-word phrases that would plausibly appear in news "
        "articles about ethnic conflict and would signal this factor.\n\n"
        f"Factor: {factor}\nDescription: {description}\n\n"
        "Return JSON: {\"phrases\": [\"...\", ...]} containing 3-6 multi-word "
        "semantic phrases (each at least 2 words) that capture this factor "
        "in the context of ethnic conflict. Phrases only, no explanations."
    )
    try:
        content = call_llm(client, [{"role": "user", "content": prompt}])
        data = parse_json(content)
        phrases = [p.strip() for p in data.get("phrases", []) if isinstance(p, str)]
        return [p for p in phrases if len(p.split()) >= 2]
    except (RuntimeError, json.JSONDecodeError, ValueError) as e:
        logging.getLogger(__name__).warning(
            "Failed to get semantic phrases for %s: %s", factor, e
        )
        return []


def scan_article(client: Groq, text: str, codes: list[dict]) -> dict[str, list[str]]:
    factor_block = "\n".join(f"- {c['factor']}: {c['description']}" for c in codes)
    prompt = (
        f"Article text:\n{text}\n\nFactors:\n{factor_block}\n\n"
        "For each factor, return exact phrases copied verbatim from the article "
        "that express that factor. Return JSON of the form "
        "{\"<factor name>\": [\"exact phrase\", ...], ...}. "
        "Only include phrases that appear verbatim in the article. "
        "Use an empty list when none apply."
    )
    try:
        content = call_llm(client, [{"role": "user", "content": prompt}])
        data = parse_json(content)
        return {
            k: [p for p in v if isinstance(p, str)]
            for k, v in data.items()
            if isinstance(v, list)
        }
    except (RuntimeError, json.JSONDecodeError, ValueError) as e:
        logging.getLogger(__name__).warning("Failed to scan article: %s", e)
        return {}


def count_occurrences(text: str, phrases: list[str]) -> int:
    text_l = text.lower()
    spans: list[tuple[int, int]] = []
    for p in phrases:
        p_l = p.lower().strip()
        if not p_l:
            continue
        start = 0
        while True:
            idx = text_l.find(p_l, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(p_l)))
            start = idx + 1
    spans.sort()
    count, last_end = 0, -1
    for s, e in spans:
        if s >= last_end:
            count += 1
            last_end = e
    return count


def write_markdown(results: list[dict], path: Path) -> None:
    lines = ["| factor | semantic_phrases | count |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {r['factor']} | {r['semantic_phrases']} | {r['count']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_articles_dir(explicit_dir: Path | None, log: logging.Logger) -> Path:
    """Find articles directory, with fallback search in common locations."""
    if explicit_dir is not None:
        if explicit_dir.exists():
            return explicit_dir
        raise FileNotFoundError(f"Specified articles directory not found: {explicit_dir.resolve()}")
    
    # Try default first
    default_dir = Path("resource/Articles")
    if default_dir.exists():
        return default_dir
    
    # Search common locations
    log.info("Default articles directory not found, searching common locations...")
    for rel_path in COMMON_ARTICLE_DIRS:
        candidate = Path(rel_path)
        if candidate.exists() and any(candidate.glob("*.html")):
            log.info("Found articles in: %s", candidate.resolve())
            return candidate
    
    # If nothing found, return default (will trigger warning later)
    log.warning("No articles directory found in common locations. Using default: %s", default_dir.resolve())
    return default_dir


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze ethnic conflict factors in HTML articles."
    )
    p.add_argument(
        "--max-articles",
        "--max-files",
        dest="max_files",
        type=int,
        default=None,
        help=f"Max articles to process (default: all; suggested cap {SUGGESTED_MAX_FILES})",
    )
    p.add_argument("--codebook", type=Path, default=Path("code-book.qdc"))
    p.add_argument("--articles-dir", type=Path, default=None, help="Directory containing HTML articles (default: auto-detect)")
    p.add_argument("--output", type=Path, default=Path("conflict_analysis_results.md"))
    return p.parse_args()


def main() -> int:
    setup_logging()
    log = logging.getLogger("conflict_analysis")
    args = parse_args()
    try:
        api_key = load_api_key()
        client = Groq(api_key=api_key)

        codes = extract_codes(args.codebook)
        log.info("Loaded %d codes from %s", len(codes), args.codebook)

        for c in codes:
            c["semantic_phrases"] = get_semantic_phrases(client, c["factor"], c["description"])
            log.info("Semantic phrases for '%s': %s", c["factor"], c["semantic_phrases"])
            time.sleep(API_SLEEP_SECONDS)

        articles_dir = find_articles_dir(args.articles_dir, log)
        if not articles_dir.exists():
            raise FileNotFoundError(
                f"Articles dir not found: {articles_dir.resolve()}. "
                f"Tried common locations: {', '.join(COMMON_ARTICLE_DIRS)}"
            )
        articles = sorted(articles_dir.glob("*.html"))
        if not articles:
            log.warning(
                "No .html files found in %s — results will be empty",
                articles_dir.resolve(),
            )
        if args.max_files is not None:
            articles = articles[: args.max_files]
        log.info("Processing %d article(s) from %s", len(articles), articles_dir.resolve())

        counts = {c["factor"]: 0 for c in codes}
        for i, art in enumerate(articles, 1):
            try:
                text = extract_text(art)
                if len(text) > MAX_ARTICLE_CHARS:
                    log.warning("Truncating %s to %d chars", art.name, MAX_ARTICLE_CHARS)
                    text = text[:MAX_ARTICLE_CHARS]
                if not text:
                    log.warning("Empty article: %s", art.name)
                    continue
                per_factor = scan_article(client, text, codes)
                for c in codes:
                    raw = per_factor.get(c["factor"], [])
                    verified = [p for p in raw if p.lower() in text.lower()]
                    counts[c["factor"]] += count_occurrences(text, verified)
                log.info("Article %d/%d processed: %s", i, len(articles), art.name)
            except (OSError, RuntimeError, ValueError) as e:
                log.error("Failed on %s: %s", art.name, e)
            time.sleep(API_SLEEP_SECONDS)

        results = [
            {
                "factor": c["factor"],
                "semantic_phrases": ", ".join(c["semantic_phrases"]),
                "count": counts[c["factor"]],
            }
            for c in codes
        ]
        write_markdown(results, args.output)
        log.info("Results written to %s", args.output)
        return 0
    except Exception:
        log.exception("Fatal error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
