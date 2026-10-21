#!/usr/bin/env python3
"""Build a BibTeX file from DOI metadata in PDFs."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests
from scholar_bibtex_pdf import _extract_front_page_fields, _extract_pdf_metadata, _extract_pdf_text_first_pages


def normalize_doi(value: str) -> str:
    """Accept a DOI, doi: identifier, or DOI resolver URL."""
    value = value.strip()

    if value.lower().startswith("doi:"):
        value = value[4:].strip()
    elif "://" in value or value.lower().startswith("doi.org/"):
        if value.lower().startswith("doi.org/"):
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"doi.org", "www.doi.org", "dx.doi.org"}:
            raise ValueError("URL must be a doi.org resolver URL")
        value = unquote(parsed.path.lstrip("/"))

    value = value.strip()
    if not re.match(r"^10\.\d{4,9}/\S+$", value):
        raise ValueError(f"Not a valid DOI identifier: {value!r}")
    return value


def fetch_bibtex(doi: str) -> str:
    """Ask the DOI resolver for a BibTeX representation."""
    resolver_url = "https://doi.org/" + quote(doi, safe="/()")
    response = requests.get(
        resolver_url,
        headers={
            "Accept": "application/x-bibtex",
            "User-Agent": "get_biblio/1.0 (DOI-to-BibTeX utility)",
        },
        timeout=30,
    )
    response.raise_for_status()

    bibtex = response.text.strip()
    if not bibtex.startswith("@"):
        raise ValueError(
            "The DOI resolver did not return BibTeX. "
            "The metadata provider may not support this format."
        )
    return bibtex + "\n"


def find_doi_in_text(text: str) -> str | None:
    """Search for a DOI pattern in text and return the first valid one."""
    # Common DOI pattern: 10.xxxx/xxxxx (with allowed characters)
    # We use a regex that matches the DOI pattern and then validate with normalize_doi
    doi_pattern = re.compile(r'\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b', re.IGNORECASE)
    for match in doi_pattern.finditer(text):
        candidate = match.group(1)
        # Clean trailing punctuation that might be captured
        candidate = candidate.rstrip('.,;:)]"\'')
        try:
            return normalize_doi(candidate)
        except ValueError:
            continue
    return None


def extract_pdf_doi(pdf_path: Path) -> str:
    """Read a DOI from PDF metadata or its text content (with progressive scanning)."""
    # 1. Metadata (including XMP via updated scholar_bibtex_pdf)
    metadata = _extract_pdf_metadata(str(pdf_path))
    raw_doi = metadata.get("DOI") or ""
    if raw_doi:
        try:
            return normalize_doi(raw_doi)
        except ValueError:
            pass

    # 2. First 5 pages (fast path)
    text = _extract_pdf_text_first_pages(str(pdf_path), n_pages=5)
    doi = find_doi_in_text(text)
    if doi:
        return doi

    # 3. Deep scan: first 20 pages, last 5 pages, then the rest (up to 50 pages total)
    try:
        from scholar_bibtex_pdf import PdfReader
        if PdfReader is not None:
            reader = PdfReader(str(pdf_path))
            total_pages = len(reader.pages)
            # Define page order: first 20, last 5, then middle (if any)
            page_indices = list(range(min(20, total_pages)))
            if total_pages > 20:
                page_indices.extend(range(max(20, total_pages - 5), total_pages))
            # Add middle pages if still not enough (up to 50 total)
            if len(page_indices) < min(50, total_pages):
                middle_start = min(20, total_pages)
                middle_end = max(20, total_pages - 5)
                page_indices.extend(range(middle_start, min(middle_end, middle_start + 30)))

            seen = set()
            for i in page_indices:
                if i in seen:
                    continue
                seen.add(i)
                page_text = reader.pages[i].extract_text() or ""
                if not page_text.strip():
                    continue
                doi = find_doi_in_text(page_text)
                if doi:
                    return doi
    except Exception:
        pass

    return ""


def set_bibtex_key(bibtex: str, key: str) -> str:
    """Replace the citation key in a single BibTeX entry."""
    updated, replacements = re.subn(
        r"(?im)^(@\s*\w+\s*[{(]\s*)[^,\s]+",
        lambda match: match.group(1) + key,
        bibtex.strip(),
        count=1,
    )
    if replacements != 1:
        raise ValueError("Could not identify a BibTeX entry key")
    return updated + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrieve BibTeX entries for PDFs in a folder using their DOIs."
    )
    parser.add_argument(
        "--pdfs-dir",
        type=Path,
        default=Path("pdf"),
        help="folder containing PDFs (searched recursively; default: pdf/)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("biblio.bib"),
        help="output BibTeX file (default: biblio.bib)",
    )
    args = parser.parse_args()

    if not args.pdfs_dir.is_dir():
        print(f"Error: PDF folder not found: {args.pdfs_dir}", file=sys.stderr)
        return 1

    entries = []
    skipped_files = []
    pdf_files = sorted(path for path in args.pdfs_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf")
    for pdf_path in pdf_files:
        filename = str(pdf_path.relative_to(args.pdfs_dir))
        try:
            doi = extract_pdf_doi(pdf_path)
            if not doi:
                remark = "DOI not found"
                skipped_files.append((filename, remark))
                print(f"Skipping {pdf_path}: {remark}", file=sys.stderr)
                continue
            entry = set_bibtex_key(fetch_bibtex(doi), f"pdf-{len(entries) + 1}")
            entries.append(entry)
            print(f"Added {pdf_path} ({doi})")
        except (ValueError, requests.RequestException, OSError, RuntimeError) as exc:
            skipped_files.append((filename, str(exc)))
            print(f"Skipping {pdf_path}: {exc}", file=sys.stderr)

    try:
        with Path("no-doi-found.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["filename", "remark"])
            writer.writerows(skipped_files)
    except OSError as exc:
        print(f"Error writing no-doi-found.csv: {exc}", file=sys.stderr)
        return 1

    try:
        args.output.write_text("\n".join(entries), encoding="utf-8")
    except OSError as exc:
        print(f"Error writing {args.output}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(entries)} BibTeX record(s) to {args.output}")
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
