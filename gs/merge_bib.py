#!/usr/bin/env python3
"""Merge two BibTeX files by DOI."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from typing import Dict, List, Tuple

import bibtexparser
from bibtexparser.model import Entry, Field


@dataclass
class Record:
    entry_type: str
    key: str
    fields: Dict[str, str]


@dataclass
class MergeSummary:
    records_read: int
    records_created: int = 0
    records_updated: int = 0
    records_deleted: int = 0
    records_matched: int = 0


def _read_bib(path: str):
    library = bibtexparser.parse_file(path)
    if library.failed_blocks:
        print(
            f"Warning: skipped {len(library.failed_blocks)} malformed BibTeX "
            f"block(s) in {path}",
            file=sys.stderr,
        )
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


def _unique_key(key: str, used_keys: set[str]) -> str:
    if key not in used_keys:
        return key
    suffix = 2
    while f"{key}_{suffix}" in used_keys:
        suffix += 1
    return f"{key}_{suffix}"


def merge_by_doi(primary_library, additional_library) -> Tuple[object, MergeSummary]:
    """Merge records by normalized DOI, filling only fields missing from primary records."""
    records: List[Record] = []
    used_keys: set[str] = set()
    doi_indices: Dict[str, int] = {}
    summary = MergeSummary(
        records_read=len(primary_library.entries) + len(additional_library.entries)
    )
    updated_indices: set[int] = set()

    for is_additional, library in (
        (False, primary_library),
        (True, additional_library),
    ):
        for entry in library.entries:
            record = _record_from_entry(entry)
            doi = _normalize_doi(record.fields.get("doi", ""))
            match_index = doi_indices.get(doi) if doi else None

            if match_index is not None:
                existing = records[match_index]
                updated = False
                for field, value in record.fields.items():
                    if value.strip() and not existing.fields.get(field, "").strip():
                        existing.fields[field] = value
                        updated = True
                if is_additional:
                    summary.records_matched += 1
                    if updated:
                        updated_indices.add(match_index)
                continue

            record.key = _unique_key(record.key, used_keys)
            used_keys.add(record.key)
            record_index = len(records)
            records.append(record)
            if doi:
                doi_indices[doi] = record_index
            if is_additional:
                summary.records_created += 1

    blocks = [
        Entry(
            record.entry_type,
            record.key,
            [Field(name, value) for name, value in record.fields.items()],
        )
        for record in records
    ]
    summary.records_updated = len(updated_indices)
    return bibtexparser.Library(blocks=blocks), summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge biblio.bib and biblio_add.bib by DOI."
    )
    parser.add_argument(
        "--primary",
        default="biblio.bib",
        help="primary BibTeX file (default: biblio.bib)",
    )
    parser.add_argument(
        "--additional",
        default="biblio_add.bib",
        help="additional BibTeX file (default: biblio_add.bib)",
    )
    parser.add_argument(
        "--output", default="bibliography.bib", help="synced bibliography output file"
    )
    parser.add_argument(
        "--summary",
        default="bibliography_summary.txt",
        help="CRUD summary output file (default: bibliography_summary.txt)",
    )
    args = parser.parse_args()

    primary_library = _read_bib(args.primary)
    additional_library = _read_bib(args.additional)
    merged_library, summary = merge_by_doi(
        primary_library, additional_library
    )
    with open(args.output, "w", encoding="utf-8") as output:
        output.write(bibtexparser.write_string(merged_library))

    summary_text = (
        "BibTeX merge CRUD summary\n"
        f"Read: {summary.records_read} records\n"
        f"Created: {summary.records_created} records\n"
        f"Updated: {summary.records_updated} records\n"
        f"Deleted: {summary.records_deleted} records\n"
        f"Matched by DOI: {summary.records_matched} records\n"
        f"Final bibliography: {len(merged_library.entries)} records ({args.output})\n"
    )
    with open(args.summary, "w", encoding="utf-8") as output:
        output.write(summary_text)
    print(summary_text, end="")


if __name__ == "__main__":
    main()