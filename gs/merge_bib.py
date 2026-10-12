#!/usr/bin/env python3
"""Merge Google Scholar and PDF BibTeX records into one bibliography."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import bibtexparser
from bibtexparser.model import Entry, Field


@dataclass
class Record:
    entry_type: str
    key: str
    fields: Dict[str, str]


def _read_bib(path: str):
    library = bibtexparser.parse_file(path)
    if library.failed_blocks:
        raise ValueError(f"Could not parse all BibTeX content in {path}")
    return library


def _record_from_entry(entry: Entry) -> Record:
    fields = {field.key.lower(): str(field.value) for field in entry.fields}
    note = fields.get("note", "")
    abstract_note = re.match(r"^\s*abstract\s*:\s*(.*)$", note, re.IGNORECASE | re.DOTALL)
    if abstract_note:
        if not fields.get("abstract", "").strip():
            fields["abstract"] = abstract_note.group(1).strip()
        fields.pop("note", None)

    return Record(
        entry_type=entry.entry_type,
        key=entry.key,
        fields=fields,
    )


def _normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi\s*:\s*", "", doi)
    return doi.rstrip(" .;,")


def _normalize_title(value: str) -> str:
    title = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    title = re.sub(r"\\[a-zA-Z]+", " ", title).casefold()
    title = re.sub(r"^\s*(?:\[(?:citation|c)\]\s*)+", " ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def _match_record(candidate: Record, records: List[Record]) -> Optional[int]:
    doi = _normalize_doi(candidate.fields.get("doi", ""))
    if doi:
        doi_matches = [
            index for index, record in enumerate(records)
            if _normalize_doi(record.fields.get("doi", "")) == doi
        ]
        if doi_matches:
            title = _normalize_title(candidate.fields.get("title", ""))
            return max(
                doi_matches,
                key=lambda index: SequenceMatcher(
                    None, title, _normalize_title(records[index].fields.get("title", ""))
                ).ratio(),
            )

    title = _normalize_title(candidate.fields.get("title", ""))
    if not title:
        return None

    exact_matches = [
        index for index, record in enumerate(records)
        if _normalize_title(record.fields.get("title", "")) == title
    ]
    if exact_matches:
        return exact_matches[0]

    if len(title) < 25:
        return None
    similarities = sorted(
        (
            SequenceMatcher(None, title, _normalize_title(record.fields.get("title", ""))).ratio(),
            index,
        )
        for index, record in enumerate(records)
        if _normalize_title(record.fields.get("title", ""))
    )
    similarities.reverse()
    if not similarities or similarities[0][0] < 0.94:
        return None
    if len(similarities) > 1 and similarities[0][0] - similarities[1][0] < 0.04:
        return None
    return similarities[0][1]


def _unique_key(key: str, used_keys: set[str]) -> str:
    if key not in used_keys:
        return key
    suffix = 2
    while f"{key}_{suffix}" in used_keys:
        suffix += 1
    return f"{key}_{suffix}"


def merge_libraries(pdf_library, scholar_library) -> Tuple[object, int, int]:
    """Merge records, returning the output library, match count, and appended count."""
    records = [_record_from_entry(entry) for entry in pdf_library.entries]
    used_keys: set[str] = set()
    for record in records:
        record.key = _unique_key(record.key, used_keys)
        used_keys.add(record.key)

    matched = 0
    appended = 0
    for entry in scholar_library.entries:
        scholar_record = _record_from_entry(entry)
        match_index = _match_record(scholar_record, records)
        if match_index is None:
            scholar_record.key = _unique_key(scholar_record.key, used_keys)
            used_keys.add(scholar_record.key)
            records.append(scholar_record)
            appended += 1
            continue

        pdf_record = records[match_index]
        for field, value in scholar_record.fields.items():
            if value.strip() and not pdf_record.fields.get(field, "").strip():
                pdf_record.fields[field] = value
        matched += 1

    blocks = [block for block in pdf_library.blocks if not isinstance(block, Entry)]
    blocks.extend(
        Entry(
            record.entry_type,
            record.key,
            [Field(name, value) for name, value in record.fields.items()],
        )
        for record in records
    )
    return bibtexparser.Library(blocks=blocks), matched, appended


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge PDF BibTeX records with Google Scholar records."
    )
    parser.add_argument("--pdf", default="from_pdfs.bib", help="PDF BibTeX input file")
    parser.add_argument("--scholar", default="citations.bib", help="Scholar BibTeX input file")
    parser.add_argument("--output", default="merge.bib", help="Merged BibTeX output file")
    args = parser.parse_args()

    pdf_library = _read_bib(args.pdf)
    scholar_library = _read_bib(args.scholar)
    merged_library, matched, appended = merge_libraries(pdf_library, scholar_library)
    with open(args.output, "w", encoding="utf-8") as output:
        output.write(bibtexparser.write_string(merged_library))

    print(
        f"Wrote {len(merged_library.entries)} records to {args.output} "
        f"({matched} matched, {appended} Scholar-only records added)."
    )


if __name__ == "__main__":
    main()