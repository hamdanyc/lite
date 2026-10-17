#!/usr/bin/env python3
"""Fetch BibTeX entries for DOI URLs listed in a CSV file."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import requests
from tqdm import tqdm

from get_biblio import fetch_bibtex, normalize_doi, set_bibtex_key


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch BibTeX entries from DOI URLs in a CSV file."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("no-doi-found.csv"),
        help="CSV input (default: no-doi-found.csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("biblio_add.bib"),
        help="BibTeX output (default: biblio_add.bib)",
    )
    args = parser.parse_args()

    try:
        with args.input.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not {"filename", "remark"}.issubset(reader.fieldnames or []):
                raise ValueError("Input CSV must contain filename and remark columns")
            rows = list(reader)
    except (OSError, csv.Error, ValueError) as exc:
        print(f"Error reading {args.input}: {exc}", file=sys.stderr)
        return 1

    entries = []
    failures = 0
    for row in tqdm(rows, desc="Processing DOI URLs", unit="PDF"):
        filename = (row.get("filename") or "").strip() or "(unknown filename)"
        remark = (row.get("remark") or "").strip()
        if remark.casefold() == "doi not found":
            tqdm.write(f"Skipping {filename}: DOI not found")
            continue
        if not remark:
            failures += 1
            tqdm.write(f"Skipping {filename}: DOI URL is blank")
            continue

        try:
            doi = normalize_doi(remark)
            bibtex = fetch_bibtex(doi)
            key = f"pdf-add-{len(entries) + 1}"
            entries.append(set_bibtex_key(bibtex, key))
            tqdm.write(f"Added {filename} ({doi})")
        except (ValueError, requests.RequestException, OSError) as exc:
            failures += 1
            tqdm.write(f"Skipping {filename}: {exc}")

    try:
        args.output.write_text("\n".join(entries), encoding="utf-8")
    except OSError as exc:
        print(f"Error writing {args.output}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Wrote {len(entries)} BibTeX record(s) to {args.output}; "
        f"{failures} row(s) failed."
    )
    return 0 if entries or not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())