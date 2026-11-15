#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PAGES_DIR="$SCRIPT_DIR/pages"
PDF_DIR="$SCRIPT_DIR/pdf"
OUTPUT_DIR="$SCRIPT_DIR/output"
URL_FILE="$OUTPUT_DIR/fup_pdf.txt"
BACKUPS_DIR="$SCRIPT_DIR/backups"

if [[ $# -lt 1 || -z "$1" ]]; then
    printf 'Usage: %s <query>\n' "${0##*/}" >&2
    exit 2
fi

query="$1"
cd "$SCRIPT_DIR"

mkdir -p "$PAGES_DIR" "$PDF_DIR" "$OUTPUT_DIR" "$BACKUPS_DIR"
# Step 1: Back up existing downloaded pages and PDFs.
BACKUP_DIR="$(mktemp -d "$BACKUPS_DIR/$(date +%Y%m%d_%H%M%S)_XXXXXX")"
cp -a "$PAGES_DIR" "$PDF_DIR" "$BACKUP_DIR/"
printf 'Backed up pages and PDFs to: %s\n' "$BACKUP_DIR"

# Step 2: Clear old downloaded pages and PDFs.
find "$PAGES_DIR" "$PDF_DIR" -type f -delete

# Step 3: Download Google Scholar result pages.
printf 'Downloading Google Scholar pages for: %s\n' "$query"
python3 "$SCRIPT_DIR/scholar_static.py" --query "$query" --output-dir "$PAGES_DIR"

# Step 4: Scrape downloaded pages and collect candidate PDF URLs.
combined_urls="$(mktemp)"
trap 'rm -f -- "$combined_urls"' EXIT
found_page=false

for html_file in "$PAGES_DIR"/*.html; do
    [[ -f "$html_file" ]] || continue
    found_page=true
    stem="${html_file##*/}"
    stem="${stem%.html}"
    printf 'Scraping %s\n' "$stem"
    python3 "$SCRIPT_DIR/scholar_scraper.py" \
        --html-file "$html_file" \
        --output "$OUTPUT_DIR/output_${stem}.csv" \
        --no-progress
    cat "$URL_FILE" >> "$combined_urls"
done

if [[ "$found_page" != true ]]; then
    printf 'No HTML pages were downloaded; skipping PDF downloads.\n' >&2
    exit 1
fi

awk 'NF && !seen[$0]++' "$combined_urls" > "$URL_FILE"
# Step 5: Download and validate candidate PDFs, then finish.
bash "$SCRIPT_DIR/scholar_fup_pdfs.sh"