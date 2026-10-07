# Google Scholar Scraper

This project implements the plan described in the project brief for scraping Google Scholar search pages and exporting a structured CSV file.

## Features

- Search by one or more keywords.
- Parse Scholar result cards with BeautifulSoup.
- Capture title, authors, abstract, citation year, and PDF link.
- Write a CSV file with the required columns.
- Respect a throttling delay between requests.
- Batch process saved Scholar HTML pages and merge them into one CSV.

## Usage

Install the dependencies:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

Run the scraper:

```bash
python3 scholar_scraper.py --keyword "deep learning" --output output_data.csv
```

You can also pass a direct URL or a local HTML file for testing:

```bash
python3 scholar_scraper.py --url "https://scholar.google.com/scholar?q=deep+learning" --output output_data.csv
python3 scholar_scraper.py --html-file tests/sample_scholar_page.html --output sample_output.csv
```

## Action: process saved HTML pages with `gs_run.sh`

This project provides a batch-processing action that reads **all** Google Scholar HTML pages saved under `pages/` and merges them into a single consolidated CSV.

Prerequisites:

- Save one Scholar results HTML page per keyword/query into the `pages/` directory (e.g. by running `scholar_scraper.py --html-file ...` to export pages, or saving search result pages manually).
- Each page is parsed individually and duplicates (rows with the same Title and Authors) are removed in the final merge.

Run the action:

```bash
bash gs_run.sh
```

This will:

1. Find every `*.html` file inside `pages/`.
2. Run `scholar_scraper.py` on each one, writing one CSV per page into `output/`.
3. Merge all per-file CSVs into a single `output/all_records.csv`, deduplicating on `(Title, Authors)`.

The final merged file is written to:

```
output/all_records.csv
```

## Output columns

- Title
- Authors
- Abstract
- Citation Details
- PDF_URL

## Ethical notes

This scraper uses a respectful delay between requests and should be used with care to avoid overloading the target service.
