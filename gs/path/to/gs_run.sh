#!/bin/bash

# Recursively find all HTML files in the pages/ folder and run scholar_scraper.py
# for each file, using the html parser.

if [ ! -d "pages/" ]; then
    echo "Error: 'pages/' directory not found."
    exit 1
fi

OUTPUT_DIR="output"
mkdir -p "$OUTPUT_DIR"

find "pages/" -type f -name "*.html" -print0 | while IFS= read -r -d '' html_file; do
    echo "Processing: $html_file"
    stem=$(basename "$html_file" .html)
    python3 scholar_scraper.py --html-file "$html_file" --output "${OUTPUT_DIR}/output_${stem}.csv"
    if [ $? -ne 0 ]; then
        echo "Failed to process: $html_file"
    fi
done

# Combine per-file outputs into a single CSV.
python3 - <<'PY'
import csv, glob, os

files = sorted(glob.glob("output/output_*.csv"))
if not files:
    print("No output CSVs generated.")
    exit(0)

fieldnames = ["Title", "Authors", "Abstract", "Citation Details", "PDF_URL"]
with open("output/all_records.csv", "w", newline="", encoding="utf-8") as out:
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    merged = set()
    count = 0
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["Title"], row["Authors"])
                if key in merged:
                    continue
                merged.add(key)
                writer.writerow(row)
                count += 1
    print(f"Merged {count} unique records from {len(files)} files -> output/all_records.csv")
PY
