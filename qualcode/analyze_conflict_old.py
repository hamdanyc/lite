"""Analyze codebook factors against a collection of HTML articles."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import unescape
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

API_BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "openai/gpt-oss-20b"


class AnalysisError(Exception):
    """An expected configuration, API, or input error."""


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        if self.ignored_depth:
            return

        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag == "meta" and attributes.get("name", "").lower() in {
            "description",
            "keywords",
            "hdl",
            "hdl_p",
            "lp",
        }:
            self.parts.append(unescape(attributes.get("content", "")))
        if attributes.get("alt"):
            self.parts.append(unescape(attributes["alt"]))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _normalize_search_text(text: str) -> str:
    parser = _ArticleTextParser()
    parser.feed(text)
    return " ".join(re.findall(r"\w+", " ".join(parser.parts).casefold()))


def _phrase_spans(phrase: str, article_tokens: list[str]) -> list[tuple[int, int]]:
    phrase_tokens = _normalize_search_text(phrase).split()
    phrase_length = len(phrase_tokens)
    if phrase_length < 2:
        return []
    return [
        (start, start + phrase_length)
        for start in range(len(article_tokens) - phrase_length + 1)
        if article_tokens[start : start + phrase_length] == phrase_tokens
    ]


def _count_phrase_occurrences(phrases: list[str], article_tokens: list[str]) -> int:
    spans = sorted(
        span
        for phrase in phrases
        for span in _phrase_spans(phrase, article_tokens)
    )
    non_overlapping: list[tuple[int, int]] = []
    for start, end in spans:
        if non_overlapping and start < non_overlapping[-1][1]:
            previous_start, previous_end = non_overlapping[-1]
            non_overlapping[-1] = (previous_start, max(previous_end, end))
        else:
            non_overlapping.append((start, end))
    return len(non_overlapping)


def _phrase_target_score(phrase: str, target: dict[str, str]) -> tuple[int, int]:
    phrase_tokens = set(_normalize_search_text(phrase).split())
    code_tokens = set(
        _normalize_search_text(
            f"{target['factor']} {target.get('description', '')}"
        ).split()
    )
    overlap = sum(
        any(
            token == code_token
            or (
                len(token) >= 6
                and len(code_token) >= 6
                and token[:6] == code_token[:6]
            )
            for code_token in code_tokens
        )
        for token in phrase_tokens
    )
    specificity = target["factor"].count(" > ")
    return overlap, specificity


def aggregate_semantic_evidence(
    targets: list[dict[str, str]],
    article_evidence: list[tuple[list[str], dict[str, list[str]]]],
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Assign duplicate normalized phrases to one best-matching code only."""
    target_by_id = {target["id"]: target for target in targets}
    phrase_owners: dict[str, str] = {}
    for _, evidence_by_id in article_evidence:
        for target in targets:
            target_id = target["id"]
            for phrase in evidence_by_id.get(target_id, []):
                phrase_key = _normalize_search_text(phrase)
                current_owner = phrase_owners.get(phrase_key)
                if current_owner is None or _phrase_target_score(
                    phrase, target
                ) > _phrase_target_score(phrase, target_by_id[current_owner]):
                    phrase_owners[phrase_key] = target_id

    terms_by_id = {target["id"]: [] for target in targets}
    counts_by_id = {target["id"]: 0 for target in targets}
    for article_tokens, evidence_by_id in article_evidence:
        for target in targets:
            target_id = target["id"]
            owned_phrases = list(
                dict.fromkeys(
                    phrase
                    for phrase in evidence_by_id.get(target_id, [])
                    if phrase_owners.get(_normalize_search_text(phrase)) == target_id
                )
            )
            terms_by_id[target_id].extend(owned_phrases)
            counts_by_id[target_id] += _count_phrase_occurrences(
                owned_phrases, article_tokens
            )
    return terms_by_id, counts_by_id


def _parse_json_object(response_text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", response_text):
        try:
            value, _ = decoder.raw_decode(response_text, match.start())
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value

        # If the response was cut off, preserve only complete top-level members.
        position = match.start() + 1
        recovered: dict[str, Any] = {}
        while position < len(response_text):
            while position < len(response_text) and response_text[position] in " \t\r\n,":
                position += 1
            if position >= len(response_text) or response_text[position] == "}":
                break
            try:
                key, position = decoder.raw_decode(response_text, position)
            except json.JSONDecodeError:
                break
            while position < len(response_text) and response_text[position].isspace():
                position += 1
            if not isinstance(key, str) or position >= len(response_text):
                break
            if response_text[position] != ":":
                break
            position += 1
            while position < len(response_text) and response_text[position].isspace():
                position += 1
            try:
                item, position = decoder.raw_decode(response_text, position)
            except json.JSONDecodeError:
                break
            recovered[key] = item
        if recovered:
            return recovered

    preview = response_text[:160].strip()
    raise AnalysisError(
        "Model response did not contain a complete JSON object or recoverable "
        f"entries (length={len(response_text)}). Preview: {preview!r}"
    )


def load_api_key(project_root: Path) -> str:
    """Load GROQ_API_KEY from the environment or a project .env file."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    env_file = project_root / ".env"
    if not api_key and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "GROQ_API_KEY":
                api_key = value.strip().strip("\"'")
                break

    if not api_key:
        raise AnalysisError(
            "GROQ_API_KEY is missing. Set it in the environment or project .env file."
        )
    return api_key


def extract_code_targets(codebook_path: Path) -> list[dict[str, str]]:
    """Return every Code element with its full hierarchical name and description."""
    try:
        root = ET.parse(codebook_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise AnalysisError(f"Could not read codebook {codebook_path}: {exc}") from exc

    targets: list[dict[str, str]] = []

    def visit(element: ET.Element, parent_names: list[str]) -> None:
        for child in element:
            if child.tag.rsplit("}", 1)[-1] != "Code":
                visit(child, parent_names)
                continue
            name = child.attrib.get("name", "").strip()
            names = parent_names + ([name] if name else [])
            if name:
                targets.append(
                    {
                        "id": str(len(targets)),
                        "factor": " > ".join(names),
                        "description": child.attrib.get("description", "").strip(),
                    }
                )
            visit(child, names)

    visit(root, [])
    if not targets:
        raise AnalysisError(f"No <Code> elements found in {codebook_path}.")
    return targets


def scan_semantic_mentions(
    targets: list[dict[str, str]], article_paths: list[Path], api_key: str
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Use Groq to find and count source-verified semantic evidence per code."""
    client = OpenAI(api_key=api_key, base_url=API_BASE_URL)
    article_evidence: list[tuple[list[str], dict[str, list[str]]]] = []
    codes_json = json.dumps(targets, ensure_ascii=False)

    total_articles = len(article_paths)
    for article_number, article_path in enumerate(article_paths, start=1):
        print(
            f"[{article_number}/{total_articles}] Scanning: {article_path.name}",
            file=sys.stderr,
            flush=True,
        )
        try:
            article_html = article_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AnalysisError(f"Could not read article {article_path}: {exc}") from exc
        article_text = _normalize_search_text(article_html)
        if not article_text:
            print(
                f"[{article_number}/{total_articles}] Skipped: no readable text",
                file=sys.stderr,
                flush=True,
            )
            continue

        prompt = (
            "You are coding historical news articles for a qualitative research "
            "study. For each code, find explicit passages in this article "
            "that express the code's concept, including clear paraphrases. Do not "
            "count mere mentions of a group or unrelated violence. Return at most "
            "three short, verbatim, contiguous phrases per code, copied from the "
            "article text. Each phrase must be 2 to 8 words and represent one "
            "occurrence; do not "
            "repeat or overlap evidence for the same code. Use an empty list when "
            "no evidence exists. Return only a JSON object mapping code ids to "
            'evidence phrase lists, e.g. {"0": ["quoted evidence"]}.\n\n'
            f"Codes: {codes_json}\n\n"
            f"Article ({article_path.name}): {article_text}"
        )
        try:
            response = client.responses.create(
                input=prompt,
                model=MODEL,
                reasoning={"effort": "low"},
                max_output_tokens=4096,
            )
            try:
                generated = _parse_json_object(response.output_text or "")
            except AnalysisError:
                if response.status != "incomplete":
                    raise
                generated = {}

            if response.status == "incomplete":
                missing_targets = [
                    target for target in targets if target["id"] not in generated
                ]
                if missing_targets:
                    retry_prompt = (
                        "For this article, find short, verbatim phrases that express "
                        "each supplied code's concept. Return at most three phrases "
                        "per code, each 2 to 8 words. Use an empty list if no evidence. "
                        'Return only JSON mapping code ids to lists, e.g. {"0": []}.\n\n'
                        f"Codes: {json.dumps(missing_targets, ensure_ascii=False)}\n\n"
                        f"Article ({article_path.name}): {article_text}"
                    )
                    retry_response = client.responses.create(
                        input=retry_prompt,
                        model=MODEL,
                        reasoning={"effort": "low"},
                        max_output_tokens=4096,
                    )
                    generated.update(
                        _parse_json_object(retry_response.output_text or "")
                    )
        except OpenAIError as exc:
            raise AnalysisError(f"Groq API request failed: {exc}") from exc
        except (AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise AnalysisError(f"Groq returned an invalid response: {exc}") from exc

        article_tokens = article_text.split()
        verified_by_id: dict[str, list[str]] = {}
        matched_codes = 0
        for target in targets:
            matches = generated.get(target["id"], [])
            if not isinstance(matches, list):
                continue
            verified = list(
                dict.fromkeys(
                    match.strip()
                    for match in matches
                    if isinstance(match, str)
                    and 2 <= len(_normalize_search_text(match).split()) <= 8
                    and _phrase_spans(match, article_tokens)
                )
            )
            verified_by_id[target["id"]] = verified
            if verified:
                matched_codes += 1
        article_evidence.append((article_tokens, verified_by_id))
        print(
            f"[{article_number}/{total_articles}] Complete: evidence for "
            f"{matched_codes}/{len(targets)} codes",
            file=sys.stderr,
            flush=True,
        )

    return aggregate_semantic_evidence(targets, article_evidence)


def count_occurrences(terms: list[str], article_paths: list[Path]) -> int:
    """Count whole, non-overlapping phrase occurrences in article text."""
    count = 0
    for article_path in article_paths:
        try:
            article_html = article_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AnalysisError(f"Could not read article {article_path}: {exc}") from exc
        article_tokens = _normalize_search_text(article_html).split()
        count += _count_phrase_occurrences(terms, article_tokens)
    return count


def analyze(
    codebook_path: Path,
    articles_dir: Path,
    api_key: str,
    max_articles: int | None = None,
) -> list[dict[str, Any]]:
    """Generate phrases, search articles, and return the requested result records."""
    if not articles_dir.is_dir():
        raise AnalysisError(f"Articles directory does not exist: {articles_dir}")
    article_paths = sorted(articles_dir.rglob("*.html"))
    if max_articles is not None:
        if max_articles < 1:
            raise AnalysisError("Maximum article count must be at least 1.")
        article_paths = article_paths[:max_articles]
    if not article_paths:
        raise AnalysisError(f"No HTML articles found in {articles_dir}.")

    targets = extract_code_targets(codebook_path)
    terms_by_id, counts_by_id = scan_semantic_mentions(
        targets, article_paths, api_key
    )
    return [
        {
            "factor": target["factor"],
            "semantic_term": ", ".join(
                sorted(
                    dict.fromkeys(terms_by_id[target["id"]]),
                    key=lambda term: (
                        -terms_by_id[target["id"]].count(term),
                        term,
                    ),
                )[:3]
            ),
            "count": counts_by_id[target["id"]],
        }
        for target in targets
    ]


def _default_path(project_root: Path, preferred: str, alternative: str) -> Path:
    preferred_path = project_root / preferred
    return preferred_path if preferred_path.exists() else project_root / alternative


def render_markdown_table(results: list[dict[str, Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    rows = [
        "# Conflict Factor Analysis",
        "",
        "| Factor | Semantic term | Count |",
        "|---|---|---:|",
    ]
    for result in results:
        semantic_term = result["semantic_term"] or "None"
        rows.append(
            "| "
            + " | ".join(
                (
                    cell(result["factor"]),
                    cell(semantic_term),
                    cell(result["count"]),
                )
            )
            + " |"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codebook",
        type=Path,
        default=_default_path(project_root, "codebook.qdc", "code-book.qdc"),
    )
    parser.add_argument(
        "--articles",
        type=Path,
        default=_default_path(project_root, "resource/Articles", "Articles"),
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        help="Read at most this many sorted HTML files (default: all files).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "analysis.md",
        help="Markdown report path (default: analysis.md in the project directory).",
    )
    args = parser.parse_args(argv)

    try:
        results = analyze(
            args.codebook,
            args.articles,
            load_api_key(project_root),
            max_articles=args.max_articles,
        )
        args.output.write_text(render_markdown_table(results), encoding="utf-8")
    except AnalysisError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error writing report to {args.output}: {exc}", file=sys.stderr)
        return 1

    print(f"Markdown report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())