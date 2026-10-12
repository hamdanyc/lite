#!/usr/bin/env python3
"""
scholar_bibtex_pdf.py

Iterate a folder of PDF files, extract bibliographic metadata from each PDF,
and write a single BibTeX file with running keys (pdf#1, pdf#2, ...).

Usage:
    python scholar_bibtex_pdf.py --pdfs-dir pdf/ --output from_pdfs.bib --limit 25

Metadata extraction is preferred over text parsing.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional PDF readers: pypdf (active maintenance) preferred, PyPDF2 fallback.
# ---------------------------------------------------------------------------
try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ModuleNotFoundError:
    try:
        from PyPDF2 import PdfReader
        from PyPDF2.errors import PyPDFError
    except ModuleNotFoundError:
        PdfReader = None

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    def tqdm(iterable=None, *args, **kwargs):
        return iterable if iterable is not None else []


# ---------------------------------------------------------------------------
# Text cleanup helpers (mirrors scholar_bibtex.py)
# ---------------------------------------------------------------------------

def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


# ---------------------------------------------------------------------------
# PDF extraction helpers
# ---------------------------------------------------------------------------

def _collect_pdf_files(pdf_dir: str) -> List[str]:
    """Recursively collect all PDF files in pdf_dir, sorted for deterministic output."""
    files: List[str] = []
    for root, _, filenames in os.walk(pdf_dir):
        for name in filenames:
            if name.lower().endswith(".pdf"):
                files.append(os.path.join(root, name))
    return sorted(files)


def _pdf_field(metadata, name: str) -> Optional[str]:
    """Read a metadata field supporting both pypdf (lowercase attributes) and PyPDF2 (dict keys)."""
    if metadata is None:
        return None
    # pypdf: attributes like metadata.author, metadata.title, metadata.creation_date
    for attr in (name.lower(), "/" + name.lower(), "/" + name):
        try:
            val = getattr(metadata, attr, None)
        except Exception:
            val = None
        if val is not None:
            return clean_text(str(val))
    # PyPDF2 / raw dict style: keys like "/Author", "/title"
    for key in (name, name.lower(), "/" + name, "/" + name.lower()):
        try:
            val = metadata.get(key)
        except Exception:
            continue
        if val is not None:
            return clean_text(str(val))
    return None


def _extract_pdf_metadata(path: str) -> Dict[str, Optional[str]]:
    """Extract embedded metadata from a PDF: title, author, year, publisher, DOI, etc."""
    if PdfReader is None:
        raise RuntimeError(
            "No PDF reader installed. Install one with:\n"
            "    python -m pip install pypdf   # preferred\n"
            "or: python -m pip install PyPDF2"
        )
    meta: Dict[str, Optional[str]] = {}
    try:
        reader = PdfReader(path)
        info = reader.metadata
        for field in ("Title", "Author", "Subject", "Keywords", "Publisher",
                      "Creator", "Producer", "CreationDate", "ModDate", "DOI"):
            val = _pdf_field(info, field)
            if val:
                meta[field] = val
        # Derive a year from creation/modification date if not present.
        if not meta.get("Year"):
            for date_field in ("CreationDate", "ModDate"):
                date_val = meta.get(date_field) or ""
                m = re.search(r"\b(?:19|20)\d{2}\b", date_val)
                if m:
                    meta["Year"] = m.group(0)
                    break
    except Exception as exc:
        print(f"  Warning: could not read metadata for {path}: {exc}", file=sys.stderr)
    return meta


def _extract_pdf_text_first_pages(path: str, n_pages: int = 2) -> str:
    """Extract text from the first N pages of a PDF as a fallback for sparse metadata."""
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(path)
        parts: List[str] = []
        for i in range(min(n_pages, len(reader.pages))):
            text = reader.pages[i].extract_text() or ""
            if clean_text(text):
                parts.append(text)
        return "\n\n".join(parts)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Citation parsing helpers (mirrors scholar_bibtex.py)
# ---------------------------------------------------------------------------

def parse_authors(author_block: str) -> List[str]:
    """Split an author block into a list of individual author names."""
    text = clean_text(author_block)
    if not text:
        return []
    text = text.replace(";", ",")
    text = re.sub(r"\s*\b(?:and|&)\b\s*", ", ", text, flags=re.IGNORECASE)
    authors = [a.strip() for a in text.split(",") if a.strip()]
    return authors


def extract_year_from_text(text: str) -> str:
    """Return the first 4-digit year found in text, or empty string."""
    m = re.search(r"\b(?:19|20)\d{2}\b", text)
    return m.group(0) if m else ""


def parse_citation(text: str) -> Tuple[str, str]:
    """Split citation text into a title part and a year."""
    text = clean_text(text)
    title_part, year = text, ""
    m = re.search(r"\b(?:19|20)\d{2}\b", text)
    if m:
        year = m.group(0)
        title_part = clean_text(text[:m.start()])
    return title_part, year


def _extract_abstract(text: str) -> str:
    """Extract abstract text up to the keywords or introduction heading."""
    match = re.search(
        r"(?ims)^\s*abstract\b\s*:?\s*(.*?)"
        r"(?=^\s*(?:keywords?|index\s+terms?)\b\s*:|"
        r"^\s*(?:\d+(?:\.\d+)*\s+)?introduction\b|\Z)",
        text,
    )
    return clean_text(match.group(1)) if match else ""


def _extract_front_page_fields(text: str) -> Dict[str, str]:
    """Extract common journal citation fields from a first-page text layout."""
    fields: Dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines()]

    volume_line = next(
        (line for line in lines if re.search(r"\bVol\.?\s*\d+", line, re.IGNORECASE)),
        "",
    )
    volume_match = re.search(
        r"\bVol\.?\s*(\d+)\s*(?:No\.?|Issue)\s*(\d+)"
        r".*?\b((?:19|20)\d{2})\b.*?(\d+)\s*[-–—]\s*(\d+)",
        volume_line,
        re.IGNORECASE,
    )
    if volume_match:
        fields["volume"] = volume_match.group(1)
        fields["number"] = volume_match.group(2)
        fields["year"] = volume_match.group(3)
        fields["pages"] = f"{volume_match.group(4)}--{volume_match.group(5)}"

    if volume_line:
        volume_index = lines.index(volume_line)
        journal = next((line for line in lines[:volume_index] if line), "")
        if journal:
            fields["publication"] = journal

    doi_match = re.search(
        r"\bDOI\s*:\s*(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        text,
        re.IGNORECASE,
    )
    if doi_match:
        fields["doi"] = doi_match.group(1).rstrip(".,;)")

    doi_line_index = next(
        (i for i, line in enumerate(lines) if re.search(r"\bDOI\s*:", line, re.IGNORECASE)),
        -1,
    )
    if doi_line_index >= 0:
        paragraphs: List[List[str]] = []
        current: List[str] = []
        for line in lines[doi_line_index + 1:]:
            if not line:
                if current:
                    paragraphs.append(current)
                    current = []
                continue
            if re.match(r"^(?:©|Published by\b)", line, re.IGNORECASE) or "://" in line:
                continue
            current.append(line)
        if current:
            paragraphs.append(current)

        if paragraphs:
            fields["title"] = clean_text(" ".join(paragraphs[0]))
        if len(paragraphs) > 1:
            author_text = " ".join(paragraphs[1])
            author_text = re.sub(r"[0-9¹²³⁴⁵⁶⁷⁸⁹⁰🖂✉]", "", author_text)
            authors = parse_authors(author_text)
            if authors:
                fields["authors"] = authors

    return fields


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------

def _build_record_from_pdf(path: str) -> Dict[str, str]:
    """Merge embedded PDF metadata with a text-extraction fallback into one record."""
    meta = _extract_pdf_metadata(path)

    record: Dict[str, str] = {
        "title": meta.get("Title") or "",
        "authors": parse_authors(meta.get("Author") or ""),
        "publication": meta.get("Publisher") or "",
        "year": meta.get("Year") or "",
        "doi": "",
        "url": "",
        "volume": "",
        "number": "",
        "pages": "",
        "publisher": "",
        "eprint": "",
        "abstract": "",
        "citation_details": "",
        "pdf_url": os.path.abspath(path),
    }

    text = _extract_pdf_text_first_pages(path)
    if text:
        record["abstract"] = _extract_abstract(text)
        page_fields = _extract_front_page_fields(text)
        for field, value in page_fields.items():
            record[field] = value

    if not record["title"]:
        if not text:
            text = _extract_pdf_text_first_pages(path)
        title_part, year = parse_citation(text)
        if title_part:
            record["title"] = title_part
            if not record["authors"]:
                record["authors"] = parse_authors(title_part + (" " + year if year else ""))
    if not record["year"] and text:
        record["year"] = extract_year_from_text(text)

    return record


# ---------------------------------------------------------------------------
# BibTeX helpers
# ---------------------------------------------------------------------------

def make_bibtex_key(rec_id: int, prefix: str = "pdf") -> str:
    """Build a running citation key: pdf#1, pdf#2, ..."""
    return f"{prefix}#{rec_id}"


def _escape_bibtex(text: str) -> str:
    """Escape a string so it is safe inside a BibTeX field value."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "{{")
    text = text.replace("}", "}}")
    return text


def entry_type(record: Dict[str, str]) -> str:
    if record.get("doi"):
        return "article"
    if record.get("publisher") or record.get("publication"):
        return "article"
    if record.get("pages"):
        return "inproceedings"
    return "misc"


def record_to_bibtex(rec_id: int, record: Dict[str, str], prefix: str = "pdf") -> str:
    """Format a record as a BibTeX entry with a running key."""
    rec_key = make_bibtex_key(rec_id, prefix=prefix)
    atype = entry_type(record)

    lines = [f"@{atype}{{{rec_key},"]

    if record.get("authors"):
        lines.append(f"    author = {{{' and '.join(record['authors'])}}},")
    if record.get("title"):
        lines.append(f"    title = {{{_escape_bibtex(record['title'])}}},")
    if record.get("publication"):
        lines.append(f"    journal = {{{_escape_bibtex(record['publication'])}}},")
    elif record.get("publisher"):
        lines.append(f"    publisher = {{{_escape_bibtex(record['publisher'])}}},")
    if record.get("year"):
        lines.append(f"    year = {record['year']},")
    if record.get("volume"):
        lines.append(f"    volume = {{{_escape_bibtex(record['volume'])}}},")
    if record.get("number"):
        lines.append(f"    number = {{{_escape_bibtex(record['number'])}}},")
    if record.get("pages"):
        lines.append(f"    pages = {{{_escape_bibtex(record['pages'])}}},")
    if record.get("abstract"):
        lines.append(f"    abstract = {{{_escape_bibtex(record['abstract'])}}},")
    if record.get("doi"):
        lines.append(f"    doi = {{{_escape_bibtex(record['doi'])}}},")
    if record.get("eprint"):
        lines.append(f"    eprint = {{{_escape_bibtex(record['eprint'])}}},")

    doi = record.get("doi", "")
    link = f"https://doi.org/{doi}" if doi else record.get("url", "") or record.get("pdf_url", "")
    if link and "/home/abi/abi-ai/gs/pdf" not in link:
        lines.append(f"    url = {{{_escape_bibtex(link)}}},")

    lines.append("}")
    return "\n".join(lines) + "\n"


def write_bibtex(records: Iterable[Dict[str, str]], output_path: str, prefix: str = "pdf") -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        handle.write("@string{scholar-tool = \"scholar_bibtex_pdf\"}\n\n")
        for rec_id, record in enumerate(records, start=1):
            handle.write(record_to_bibtex(rec_id, record, prefix=prefix))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iterate a folder of PDFs and extract bibliographic metadata as BibTeX."
    )
    parser.add_argument(
        "--pdfs-dir",
        required=True,
        help="Path to the folder containing PDF files to process (walked recursively).",
    )
    parser.add_argument(
        "--output",
        default="from_pdfs.bib",
        help="Path to write the resulting BibTeX file (default: from_pdfs.bib).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of PDFs to process (default: 25; use 0 for no limit).",
    )
    parser.add_argument(
        "--keyword",
        nargs="+",
        help="Only keep records whose title, authors, or year contains one of these words.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the progress bar.",
    )
    parser.add_argument(
        "--prefix",
        default="pdf",
        help="BibTeX citation-key prefix (default: pdf), producing keys pdf#1, pdf#2, ...",
    )
    args = parser.parse_args()

    if PdfReader is None:
        print("A PDF reader library is required. Install one with:")
        print("    python -m pip install pypdf   # preferred")
        print("or: python -m pip install PyPDF2")
        sys.exit(1)

    if not os.path.isdir(args.pdfs_dir):
        print(f"Error: --pdfs-dir '{args.pdfs_dir}' is not a directory.")
        sys.exit(1)

    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    pdf_files = _collect_pdf_files(args.pdfs_dir)
    if args.limit:
        pdf_files = pdf_files[:args.limit]
    if not pdf_files:
        print(f"No PDF files found in {args.pdfs_dir}.")
        sys.exit(1)

    progress_enabled = not args.no_progress
    if progress_enabled:
        print(f"Found {len(pdf_files)} PDF file(s) in {args.pdfs_dir}")

    records: List[Dict[str, str]] = []
    skipped = 0
    failed = 0

    for path in tqdm(
        pdf_files,
        disable=not progress_enabled,
        desc="Extracting PDF metadata",
        unit="file",
    ):
        try:
            record = _build_record_from_pdf(path)
        except Exception as exc:
            failed += 1
            if progress_enabled:
                print(f"  Error reading {path}: {exc}", file=sys.stderr)
            continue

        title = record.get("title", "")
        if not title:
            skipped += 1
            continue
        if args.keyword:
            key = " ".join([title] + record["authors"] + [record["year"]]).lower()
            if not any(kw.lower() in key for kw in " ".join(args.keyword).split()):
                skipped += 1
                continue

        records.append(record)

    if progress_enabled:
        print(f"Wrote {len(records)} record(s); skipped {skipped} (empty title); failed {failed}")

    write_bibtex(records, args.output, prefix=args.prefix)
    print(f"BibTeX written to {args.output}")


if __name__ == "__main__":
    main()
