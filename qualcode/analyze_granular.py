import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from dotenv import load_dotenv
    from groq import APIError as GroqAPIError, Groq, RateLimitError as GroqRateLimitError
    from openai import APIError as OpenAIAPIError, OpenAI, RateLimitError as OpenAIRateLimitError
except ImportError as exc:
    sys.stderr.write(
        f"Missing dependency: {exc.name}. "
        "Run: pip install -r requirements.txt\n"
    )
    raise SystemExit(1)

MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "openrouter": "deepseek/deepseek-v4.1-flash-1017",
}
API_ERRORS = (GroqAPIError, OpenAIAPIError)
RATE_LIMIT_ERRORS = (GroqRateLimitError, OpenAIRateLimitError)
MAX_ARTICLE_CHARS = 20000
API_SLEEP_SECONDS = 0.5
MAX_RETRIES = 3
SUGGESTED_MAX_FILES = 25
OUTPUT_DIR = Path("output")
RESULT_CSV_FIELDS = [
    "file-id",
    "main factor",
    "sub factor",
    "sub level factor",
    "semantic term",
    "count",
]
CODEBOOK_CSV_FIELDS = [
    "main factor",
    "main factor name",
    "sub factor",
    "sub factor name",
    "sub level factor",
    "sub level factor name",
    "description",
]
FILEID_CSV_FIELDS = ["file-id", "file-name"]
COMMON_ARTICLE_DIRS = [
    "data",
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_api_key(provider: str = "groq") -> str:
    load_dotenv()
    env_var = "GROQ_API_KEY" if provider == "groq" else "OPENROUTER_API_KEY"
    key = os.getenv(env_var, "").strip()
    if not key:
        raise OSError(
            f"{env_var} is missing. Set it in the environment or project .env file."
        )
    return key


def create_client(provider: str, api_key: str) -> Groq | OpenAI:
    if provider == "groq":
        return Groq(api_key=api_key)
    return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def extract_codes(codebook_path: Path) -> list[dict]:
    resolved = codebook_path.resolve()
    if not codebook_path.exists():
        raise FileNotFoundError(f"Codebook not found: {resolved}")
    root = ET.parse(codebook_path).getroot()
    codes: list[dict] = []

    def visit(
        parent: ET.Element,
        parent_path: str,
        main_factor: str = "",
        main_factor_name: str = "",
        sub_factor: str = "",
        sub_factor_name: str = "",
        depth: int = 0,
    ) -> None:
        children = [child for child in parent if child.tag.split("}")[-1] == "Code"]
        for index, el in enumerate(children, 1):
            name = (el.get("name") or el.get("Name") or "").strip()
            if not name:
                continue
            current_depth = depth + 1
            current_main = str(index) if current_depth == 1 else main_factor
            current_sub = (
                f"{current_main}.{index}" if current_depth == 2
                else sub_factor
            )
            current_main_name = name if current_depth == 1 else main_factor_name
            current_sub_name = name if current_depth == 2 else sub_factor_name
            sub_level = ""
            if current_depth == 3:
                sub_level = f"{sub_factor}{chr(ord('a') + index - 1)}"
            factor_path = f"{parent_path} > {name}" if parent_path else name
            description = (el.get("description") or el.get("Description") or "").strip()
            if not description:
                for child in el:
                    if child.tag.split("}")[-1] in ("Description", "Text", "Comment") and child.text:
                        description = child.text.strip()
                        break
            codes.append(
                {
                    "factor": factor_path,
                    "description": description or name,
                    "main_factor": current_main,
                    "main_factor_name": current_main_name,
                    "sub_factor": current_sub if current_depth >= 2 else "",
                    "sub_factor_name": current_sub_name if current_depth >= 2 else "",
                    "sub_level_factor": sub_level,
                    "sub_level_factor_name": name if current_depth == 3 else "",
                }
            )
            visit(
                el,
                factor_path,
                current_main,
                current_main_name,
                current_sub,
                current_sub_name,
                current_depth,
            )

    code_container = next(
        (
            element
            for element in root.iter()
            if any(child.tag.split("}")[-1] == "Code" for child in element)
        ),
        root,
    )
    visit(code_container, "")
    if not codes:
        raise ValueError(f"No <Code> elements found in {resolved}")
    return codes


def extract_text(text_path: Path) -> str:
    raw = text_path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"\s+", " ", raw).strip()


def call_llm(
    client: Groq | OpenAI,
    messages: list[dict],
    json_mode: bool = True,
    model: str = MODELS["groq"],
) -> str:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            kwargs = {"model": model, "messages": messages, "temperature": 0}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except RATE_LIMIT_ERRORS as e:
            last_err = e
            time.sleep(2 ** attempt)
        except API_ERRORS as e:
            last_err = e
            logging.getLogger(__name__).warning(
                "LLM API error (attempt %d): %s", attempt + 1, e
            )
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} retries: {last_err}")


def parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


def get_semantic_phrases(
    client: Groq | OpenAI,
    factor: str,
    description: str,
    model: str = MODELS["groq"],
) -> list[str]:
    prompt = (
        "You are analyzing qualitative interview data. Given a factor from qualitative survey"
        "codebook, produce multi-word phrases that would plausibly appears"
        "as constructs and would signal this factor.\n\n"
        f"Factor: {factor}\nDescription: {description}\n\n"
        "Return JSON: {\"phrases\": [\"...\", ...]} containing 3-6 multi-word "
        "semantic phrases (each at least 2 words) that capture this factor "
        "in the context of a qualitative research. Phrases only, no explanations."
    )
    try:
        content = call_llm(client, [{"role": "user", "content": prompt}], model=model)
        data = parse_json(content)
        phrases = [p.strip() for p in data.get("phrases", []) if isinstance(p, str)]
        return [p for p in phrases if len(p.split()) >= 2]
    except (RuntimeError, json.JSONDecodeError, ValueError) as e:
        logging.getLogger(__name__).warning(
            "Failed to get semantic phrases for %s: %s", factor, e
        )
        return []


def scan_article(
    client: Groq | OpenAI,
    text: str,
    codes: list[dict],
    model: str = MODELS["groq"],
) -> dict[str, list[str]]:
    factor_block = "\n".join(f"- {c['factor']}: {c['description']}" for c in codes)
    prompt = (
        f"interview text:\n{text}\n\nFactors:\n{factor_block}\n\n"
        "For each factor, return exact phrases copied verbatim from the article "
        "that express that factor. Return JSON of the form "
        "{\"<factor name>\": [\"exact phrase\", ...], ...}. "
        "Only include phrases that appear verbatim in the article. "
        "Use an empty list when none apply."
    )
    try:
        content = call_llm(client, [{"role": "user", "content": prompt}], model=model)
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
    return len(find_occurrences(text, phrases))


def find_occurrences(text: str, phrases: list[str]) -> list[str]:
    text_l = text.lower()
    spans: list[tuple[int, int, str]] = []
    for p in phrases:
        p_l = p.lower().strip()
        if not p_l:
            continue
        start = 0
        while True:
            idx = text_l.find(p_l, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(p_l), p.strip()))
            start = idx + 1
    spans.sort(key=lambda span: (span[0], span[1]))
    matches: list[str] = []
    last_end = -1
    for s, e, phrase in spans:
        if s >= last_end:
            matches.append(phrase)
            last_end = e
    return matches


def write_markdown(results: list[dict], path: Path) -> None:
    lines = ["| factor | semantic_phrases | count |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {r['factor']} | {r['semantic_phrases']} | {r['count']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(rows: list[dict], path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_articles_dir(explicit_dir: Path | None, log: logging.Logger) -> Path:
    """Find articles directory, with fallback search in common locations."""
    if explicit_dir is not None:
        if explicit_dir.exists():
            return explicit_dir
        raise FileNotFoundError(f"Specified articles directory not found: {explicit_dir.resolve()}")
    
    # Try default first
    default_dir = Path("data")
    if default_dir.exists():
        return default_dir
    
    # Search common locations
    log.info("Default articles directory not found, searching common locations...")
    for rel_path in COMMON_ARTICLE_DIRS:
        candidate = Path(rel_path)
        if candidate.exists() and any(candidate.glob("*.txt")):
            log.info("Found articles in: %s", candidate.resolve())
            return candidate
    
    # If nothing found, return default (will trigger warning later)
    log.warning("No articles directory found in common locations. Using default: %s", default_dir.resolve())
    return default_dir


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze qualitative factors in text files."
    )
    p.add_argument(
        "--max-articles",
        "--max-files",
        dest="max_files",
        type=int,
        default=None,
        help=f"Max articles to process (default: all; suggested cap {SUGGESTED_MAX_FILES})",
    )
    p.add_argument("--codebook", type=Path, default=Path("code-book-genai.qdc"))
    p.add_argument(
        "--provider",
        choices=tuple(MODELS),
        default="groq",
        help="LLM provider (default: groq)",
    )
    p.add_argument("--articles-dir", type=Path, default=None, help="Directory containing .txt articles (default: data)")
    p.add_argument(
        "--output", type=Path, default=OUTPUT_DIR / "qualitative_analysis_results.md"
    )
    p.add_argument(
        "--csv-output",
        type=Path,
        default=OUTPUT_DIR / "qualitative_analysis_granular.csv",
        help="CSV path for article-level semantic term occurrences",
    )
    return p.parse_args()


def main() -> int:
    setup_logging()
    log = logging.getLogger("qualitative_analysis")
    args = parse_args()
    try:
        api_key = load_api_key(args.provider)
        client = create_client(args.provider, api_key)
        model = MODELS[args.provider]
        log.info("Using %s provider with model %s", args.provider, model)

        codes = extract_codes(args.codebook)
        log.info("Loaded %d codes from %s", len(codes), args.codebook)

        for c in codes:
            c["semantic_phrases"] = get_semantic_phrases(
                client, c["factor"], c["description"], model=model
            )
            log.info("Semantic phrases for '%s': %s", c["factor"], c["semantic_phrases"])
            time.sleep(API_SLEEP_SECONDS)

        articles_dir = find_articles_dir(args.articles_dir, log)
        if not articles_dir.exists():
            raise FileNotFoundError(
                f"Articles dir not found: {articles_dir.resolve()}. "
                f"Tried common locations: {', '.join(COMMON_ARTICLE_DIRS)}"
            )
        articles = sorted(articles_dir.glob("*.txt"))
        if not articles:
            log.warning(
            "No .txt files found in %s — results will be empty",
                articles_dir.resolve(),
            )
        if args.max_files is not None:
            articles = articles[: args.max_files]
        log.info("Processing %d article(s) from %s", len(articles), articles_dir.resolve())
        fileid_rows = [
            {"file-id": f"id-{i}", "file-name": article.name}
            for i, article in enumerate(articles, 1)
        ]

        counts = {c["factor"]: 0 for c in codes}
        csv_rows: list[dict] = []
        for i, art in enumerate(articles, 1):
            try:
                text = extract_text(art)
                if len(text) > MAX_ARTICLE_CHARS:
                    log.warning("Truncating %s to %d chars", art.name, MAX_ARTICLE_CHARS)
                    text = text[:MAX_ARTICLE_CHARS]
                if not text:
                    log.warning("Empty article: %s", art.name)
                    continue
                per_factor = scan_article(client, text, codes, model=model)
                for c in codes:
                    raw = per_factor.get(c["factor"], [])
                    verified = [p for p in raw if p.lower() in text.lower()]
                    occurrences = find_occurrences(text, verified)
                    counts[c["factor"]] += len(occurrences)
                    for term in occurrences:
                        csv_rows.append(
                            {
                                "file-id": f"id-{i}",
                                "main factor": c["main_factor"],
                                "sub factor": c["sub_factor"],
                                "sub level factor": c["sub_level_factor"],
                                "semantic term": term,
                                "count": 1,
                            }
                        )
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
        write_csv(csv_rows, args.csv_output, RESULT_CSV_FIELDS)
        log.info("Granular CSV written to %s", args.csv_output)
        codebook_rows = [
            {
                "main factor": code["main_factor"],
                "main factor name": code["main_factor_name"],
                "sub factor": code["sub_factor"],
                "sub factor name": code["sub_factor_name"],
                "sub level factor": code["sub_level_factor"],
                "sub level factor name": code["sub_level_factor_name"],
                "description": code["description"],
            }
            for code in codes
        ]
        write_csv(codebook_rows, OUTPUT_DIR / "codebook.csv", CODEBOOK_CSV_FIELDS)
        write_csv(fileid_rows, OUTPUT_DIR / "fileid.csv", FILEID_CSV_FIELDS)
        log.info("Codebook lookup written to %s", OUTPUT_DIR / "codebook.csv")
        log.info("File ID lookup written to %s", OUTPUT_DIR / "fileid.csv")
        return 0
    except Exception:
        log.exception("Fatal error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
