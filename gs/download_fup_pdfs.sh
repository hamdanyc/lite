#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
URL_FILE="$SCRIPT_DIR/output/fup_pdf.txt"
OUTPUT_DIR="$SCRIPT_DIR/articles"
next_index=1
downloaded=0
failed=0

if [[ ! -f "$URL_FILE" ]]; then
    printf 'URL list not found: %s\n' "$URL_FILE" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    printf 'curl is required to download PDFs.\n' >&2
    exit 1
fi

if ! command -v pdfinfo >/dev/null 2>&1; then
    printf 'pdfinfo is required to validate PDFs (install poppler-utils).\n' >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

for existing_pdf in "$OUTPUT_DIR"/pdf-*.pdf; do
    [[ -e "$existing_pdf" ]] || continue
    filename="${existing_pdf##*/}"
    if [[ "$filename" =~ ^pdf-([0-9]+)\.pdf$ ]]; then
        existing_index=$((10#${BASH_REMATCH[1]}))
        if (( existing_index >= next_index )); then
            next_index=$((existing_index + 1))
        fi
    fi
done

while IFS= read -r url || [[ -n "$url" ]]; do
    url="${url#"${url%%[![:space:]]*}"}"
    url="${url%"${url##*[![:space:]]}"}"

    [[ -z "$url" || "$url" == \#* ]] && continue

    if [[ "$url" != http://* && "$url" != https://* ]]; then
        printf 'Skipping non-HTTP URL: %s\n' "$url" >&2
        failed=$((failed + 1))
        continue
    fi

    while [[ -e "$OUTPUT_DIR/pdf-$next_index.pdf" ]]; do
        next_index=$((next_index + 1))
    done

    temp_path="$(mktemp "$OUTPUT_DIR/.pdf-download.XXXXXX")" || {
        printf 'Could not create a temporary file in %s\n' "$OUTPUT_DIR" >&2
        exit 1
    }

    if ! curl --fail --location --silent --show-error --max-time 90 \
        --output "$temp_path" "$url"; then
        printf 'Download failed: %s\n' "$url" >&2
        rm -f -- "$temp_path"
        failed=$((failed + 1))
        continue
    fi

    if ! pdfinfo "$temp_path" >/dev/null 2>&1; then
        printf 'Downloaded response is not a valid readable PDF: %s\n' "$url" >&2
        rm -f -- "$temp_path"
        failed=$((failed + 1))
        continue
    fi

    destination="$OUTPUT_DIR/pdf-$next_index.pdf"
    if mv -- "$temp_path" "$destination"; then
        printf 'Saved valid PDF: %s\n' "$destination"
        downloaded=$((downloaded + 1))
        next_index=$((next_index + 1))
    else
        printf 'Could not move validated PDF to %s\n' "$destination" >&2
        rm -f -- "$temp_path"
        failed=$((failed + 1))
    fi
done < "$URL_FILE"

printf 'Finished: %s valid PDFs saved; %s URLs failed or were rejected.\n' \
    "$downloaded" "$failed"

if (( failed > 0 )); then
    exit 1
fi