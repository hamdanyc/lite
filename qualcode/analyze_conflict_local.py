"""Analyze conflict factors with a local llama.cpp OpenAI-compatible server.

Install the optional server package, then start the server separately:
pip install 'llama-cpp-python[server]'
python -m llama_cpp.server --model /mnt/abi-ai/gguf-model/MiniCPM5-2B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8000 --model_alias local-model

Run this script in another terminal:
python analyze_conflict_local.py --max-articles 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from analyze_conflict_old import (
    AnalysisError,
    _count_phrase_occurrences,
    _default_path,
    _normalize_search_text,
    _parse_json_object,
    _phrase_spans,
    aggregate_semantic_evidence,
    extract_code_targets,
    render_markdown_table,
)

DEFAULT_MODEL_PATH = Path(
    "/mnt/abi-ai/gguf-model/gemma-4-E2B-it-Q4_0.gguf"
)
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL_NAME = "local-model"


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def scan_semantic_mentions(
    targets: list[dict[str, str]],
    article_paths: list[Path],
    base_url: str = DEFAULT_BASE_URL,
    model_name: str = DEFAULT_MODEL_NAME,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Ask the local model for source-grounded phrases and count whole matches."""
    client = OpenAI(api_key="local", base_url=base_url)
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
            "For each research code, find up to three short, verbatim, contiguous "
            "phrases from this article that clearly express the code's concept. "
            "Use the code description to distinguish related concepts. Do not count "
            "mere mentions of a group or unrelated violence. Each phrase must be "
            "2 to 8 words and copied exactly from the article text. Return an empty "
            "list when there is no evidence. Output only a JSON object mapping code "
            'ids to lists, for example {"0": ["quoted evidence"]}.\n\n'
            f"Codes: {codes_json}\n\n"
            f"Article ({article_path.name}): {article_text}"
        )

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "Return only valid JSON. Follow the requested schema exactly.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096,
            )
            choice = response.choices[0]
            response_text = _message_content_text(choice.message.content)
            try:
                generated = _parse_json_object(response_text)
            except AnalysisError:
                if choice.finish_reason != "length":
                    raise
                generated = {}

            if choice.finish_reason == "length":
                missing_targets = [
                    target for target in targets if target["id"] not in generated
                ]
                if missing_targets:
                    retry_prompt = (
                        "Return evidence phrases for these remaining codes only. "
                        "Use exact 2 to 8 word quotes from the article or an empty "
                        'list. Return JSON mapping ids to lists, e.g. {"0": []}.\n\n'
                        f"Codes: {json.dumps(missing_targets, ensure_ascii=False)}\n\n"
                        f"Article ({article_path.name}): {article_text}"
                    )
                    retry_response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": "Return only valid JSON following the requested schema.",
                            },
                            {"role": "user", "content": retry_prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        max_tokens=4096,
                    )
                    retry_text = _message_content_text(
                        retry_response.choices[0].message.content
                    )
                    generated.update(_parse_json_object(retry_text))
        except OpenAIError as exc:
            command = (
                "python -m llama_cpp.server --model "
                f"{DEFAULT_MODEL_PATH} --host 127.0.0.1 --port 8080 "
                f"--model_alias {model_name}"
            )
            raise AnalysisError(
                f"Could not reach llama.cpp server at {base_url}: {exc}. "
                f"Start it with: {command}"
            ) from exc
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AnalysisError(f"Local model returned an invalid response: {exc}") from exc

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


def analyze_local(
    codebook_path: Path,
    articles_dir: Path,
    model_path: Path,
    base_url: str = DEFAULT_BASE_URL,
    model_name: str = DEFAULT_MODEL_NAME,
    max_articles: int | None = None,
) -> list[dict[str, Any]]:
    if not model_path.is_file():
        raise AnalysisError(f"Local GGUF model file does not exist: {model_path}")
    if not articles_dir.is_dir():
        raise AnalysisError(f"Articles directory does not exist: {articles_dir}")

    article_paths = sorted(articles_dir.rglob("*.txt"))
    if max_articles is not None:
        if max_articles < 1:
            raise AnalysisError("Maximum article count must be at least 1.")
        article_paths = article_paths[:max_articles]
    if not article_paths:
        raise AnalysisError(f"No HTML articles found in {articles_dir}.")

    targets = extract_code_targets(codebook_path)
    terms_by_id, counts_by_id = scan_semantic_mentions(
        targets, article_paths, base_url, model_name
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


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-path", type=Path, default=DEFAULT_MODEL_PATH
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--codebook",
        type=Path,
        default=_default_path(project_root, "code-book-genai.qdc", "code-book.qdc"),
    )
    parser.add_argument(
        "--articles",
        type=Path,
        default=_default_path(project_root, "data", "data"),
    )
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--output", type=Path, default=project_root / "analysis_local.md")
    args = parser.parse_args(argv)

    try:
        results = analyze_local(
            args.codebook,
            args.articles,
            args.model_path,
            base_url=args.base_url,
            model_name=args.model_name,
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