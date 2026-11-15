# Google Scholar Scraper & BibTeX Toolkit

A comprehensive toolkit for scraping Google Scholar, extracting bibliographic metadata from PDFs, and managing BibTeX libraries. Designed for researchers who need to collect, organize, and export academic references efficiently.

## Features

- **Google Scholar Downloading** – Fetch result pages for a query into local HTML files, with browser-based fetching and captcha handling
- **Google Scholar Scraping** – Parse saved HTML pages and batch-process directories of saved pages
- **BibTeX Generation** – Convert scraped records or PDF metadata into valid BibTeX entries
- **PDF Metadata Extraction** – Parse title, authors, year, abstract, and DOI from PDF files
- **PDF Merging** – Combine multiple PDF files into batch files for processing or archiving
- **BibTeX Management** – Merge, deduplicate, and summarize BibTeX libraries
- **Responsible Scraping** – Built-in throttling, retry logic, and rate-limit handling

---

# Workflows

## Run the Complete Scholar-to-PDF Workflow

Run the end-to-end workflow with a search query:

```bash
./main.sh "machine learning survey"
```

`main.sh` runs these steps:

1. Copies the current `pages/` and `pdf/` directories into a unique timestamped directory under `backups/`.
2. Clears files from `pages/` and `pdf/`, preserving the directories.
3. Downloads the default 25 Google Scholar result pages.
4. Scrapes each page, writes page-level CSV files, and combines unique PDF candidate URLs in `output/fup_pdf.txt`.
5. Downloads and validates candidate PDFs into `pdf/`, then exits.

The downloader requires `curl` and `pdfinfo` (provided by `poppler-utils` on Debian/Ubuntu). The Scholar page downloader uses Selenium/Chrome by default and may require solving a captcha in a visible browser.

## 1. Download Google Scholar Pages

`scholar_static.py` fetches Google Scholar result pages for a query and saves them as numbered HTML files (e.g. `1.html`, `2.html`, …) in the output directory. These files are the input for the scraping step below.

```bash
python3 scholar_static.py --query "machine learning survey" --pages 25
```

By default it drives a real headless Chrome browser via Selenium (Google Scholar aggressively rate-limits plain HTTP clients). If Selenium is not installed, or `--no-browser` is passed, it falls back to plain `requests`.

If a captcha is served while running headless, the script automatically restarts the browser in headful mode so you can solve it; the solved session is stored in the persistent profile directory (`--profile-dir`) and reused by later runs. You can also start directly in headful mode with `--headful`.

| Option | Description | Default |
|--------|-------------|---------|
| `--query` | Search query (required) | – |
| `--pages` | Number of result pages to download | `25` |
| `--output-dir` | Directory to store downloaded HTML | `pages` |
| `--profile-dir` | Persistent Chrome profile directory (reused across runs to reduce captchas) | `.chrome-profile` |
| `--delay` | Seconds to wait between requests | `7.0` |
| `--timeout` | Per-request timeout (seconds) | `30.0` |
| `--wait` | Seconds to wait for the browser to load each page | `10.0` |
| `--max-retries` | Max retries per page | `3` |
| `--year-from` | Only include results published this year or later (`0` disables) | `2024` |
| `--no-browser` | Use plain `requests` instead of a headless browser | `False` |
| `--headful` | Run a visible browser (to solve a captcha manually) | `False` |

## 2. Scrape Google Scholar

| Method | Description | Output |
|--------|-------------|--------|
| **Parse saved HTML** | Process one locally saved Google Scholar results page | CSV, `output/fup_pdf.txt`, and any accessible PDFs |
| **Batch process** | Recursively scan `pages/` and merge records | `output/all_records.csv` + per-page CSVs |

For a single page, run the scraper and then the candidate downloader:

```bash
python3 scholar_scraper.py --html-file pages/ml_5.html --output output/output_ml_5.csv --no-progress
bash scholar_fup_pdfs.sh
```

The scraper writes distinct candidate links to `output/fup_pdf.txt` and attempts to download valid, accessible PDFs to `pdf/pdf-N.pdf`. `scholar_fup_pdfs.sh` retries the URLs in that list, validates each response with `pdfinfo`, and continues numbering after the highest existing `pdf-N.pdf`. HTML error pages, blocked responses, and invalid PDFs are discarded.

**Batch processing (`path/to/gs_run.sh`)** recursively scans `pages/`, extracts records from each HTML file, and merges them into `output/all_records.csv` with deduplication by title and authors. Since each scraper invocation rewrites `output/fup_pdf.txt`, after a batch run that file contains candidates from the last processed HTML page only.

## 3. Generate BibTeX from Scraped Data

```bash
# Basic conversion
python3 scholar_bibtex.py --input scraped_data.csv --output library.bib

# With options
python3 scholar_bibtex.py --input data.csv --output library.bib --limit 100 --delay 5.0
```

## 4. Extract Metadata from PDFs

| Tool | Purpose | Output |
|------|---------|--------|
| `scholar_bibtex_pdf.py` | Parse PDF metadata (title, authors, year, abstract) → BibTeX | `output.bib` + `pdf_src.csv` (cross-reference) |
| `get_biblio.py` | Enhanced extraction with DOI lookup → BibTeX | `biblio.bib` + `no-doi-found.csv` (manual DOI entry) |

```bash
# Extract from PDFs (basic)
python3 scholar_bibtex_pdf.py --pdfs-dir ./pdfs --output from_pdfs.bib --limit 50

# Extract with DOI enrichment
python3 get_biblio.py --pdfs-dir ./pdfs --output biblio.bib
```

## 5. Manage BibTeX Libraries

```bash
# Merge two BibTeX files with deduplication and summary
python3 merge_bib.py --primary main.bib --additional new.bib --output merged.bib --summary merge_report.txt
```

**Merge features:**
- Deduplicates by DOI, title+authors, or BibTeX key
- Preserves the most complete record
- Generates a CRUD summary (Created, Retained, Updated, Deleted)

## 6. Merge PDFs

`merge_pdfs.py` merges multiple PDF files into larger batch files, useful for combining downloaded PDFs for processing or archiving. Use as sources to Gemini notebooks.

```bash
# Basic PDF merging
python3 merge_pdfs.py --input-dir uploaded --output-dir pdf --limit-files 50 --limit-words 500000
```

**Merge features:**
- Combines PDF files into batches with configurable limits
- Limits by number of files (default: 50) and estimated word count (default: 500,000)
- Preserves original PDF content and order
- Creates named output files (`src_batch_1.pdf`, `src_batch_2.pdf`, etc.)
- Handles PDF parsing errors gracefully

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `--input-dir` | Directory containing PDF files to merge | `uploaded` |
| `--output-dir` | Directory to save merged PDF batches | `pdf` |
| `--limit-files` | Maximum number of files per batch | `50` |
| `--limit-words` | Maximum estimated words per batch | `500000` |

## 7. Extract Metadata from PDFs

| Tool | Purpose | Output |
|------|---------|--------|
| `scholar_bibtex_pdf.py` | Parse PDF metadata (title, authors, year, abstract) → BibTeX | `output.bib` + `pdf_src.csv` (cross-reference) |
| `get_biblio.py` | Enhanced extraction with DOI lookup → BibTeX | `biblio.bib` + `no-doi-found.csv` (manual DOI entry) |

```bash
# Extract from PDFs (basic)
python3 scholar_bibtex_pdf.py --pdfs-dir ./pdfs --output from_pdfs.bib --limit 50

# Extract with DOI enrichment
python3 get_biblio.py --pdfs-dir ./pdfs --output biblio.bib
```

---

# Input-Output

## Input Formats

| Format | Description |
|--------|-------------|
| **HTML** | Saved Google Scholar results pages |
| **PDF** | PDF files for metadata extraction |
| **CSV** | Intermediate structured data from scraper |
| **BibTeX** | Existing bibliography files for merging |

## Output Formats

### Structured Data (CSV)

| Field Category | Example Fields |
|----------------|----------------|
| **Core Metadata** | Title, Authors, Year, Abstract |
| **Source Details** | Venue, Publisher, DOI, URL |
| **Identifiers** | Cluster ID, Citation ID, Internal ID |
| **Metrics** | Citation count |
| **File References** | PDF URL, Local file path |

### Bibliography Formats (BibTeX)

Automatically classified entry types:
- `@article` – Journal papers
- `@inproceedings` – Conference papers
- `@book` – Books
- `@phdthesis` / `@mastersthesis` – Theses
- `@techreport` – Technical reports
- `@misc` – Fallback/generic

---

# Configuration

## Common Options

| Option | Description | Typical Default |
|--------|-------------|-----------------|
| `--input` / `--input-dir` | Source file or directory | – |
| `--output` | Output file path | `output.{ext}` |
| `--format` | Output format (bib, csv) | `csv` / `bib` |
| `--limit` | Max records to process | Unlimited |
| `--delay` | Delay between PDF download requests (seconds) | `7.0` (scraper) / `5.0` (bibtex) |
| `--max-retries` | Retry attempts for failures | `3` |
| `--timeout` | Operation timeout (seconds) | `30.0` |
| `--no-progress` | Disable progress indicators | `False` |
| `--verbose` | Enable detailed logging | `False` |

## Download-Specific Options

| Option | Description |
|--------|-------------|
| `--query` | Search query to download pages for (required) |
| `--pages` | Number of result pages to download |
| `--output-dir` | Directory to store downloaded HTML |
| `--profile-dir` | Persistent Chrome profile directory |
| `--wait` | Seconds to wait for the browser to load each page |
| `--year-from` | Only include results published this year or later |
| `--no-browser` | Use plain `requests` instead of a headless browser |
| `--headful` | Run a visible browser to solve a captcha manually |

## Scraper-Specific Options

| Option | Description |
|--------|-------------|
| `--html-file` | Required local HTML file to parse |
| `--output` | CSV output path |
| `--limit` | Maximum records to export |
| `--delay` | Delay between PDF download requests |
| `--no-progress` | Disable progress display |

## Extraction-Specific Options

| Option | Description |
|--------|-------------|
| `--pdfs-dir` | Directory containing PDF files |
| `--citations-limit` | Max citations to fetch per record |
| `--citation-timeout` | Timeout for citation export (seconds) |
| `--lookup-doi` | Enable external DOI lookup (get_biblio.py) |

## Merge-Specific Options

| Option | Description |
|--------|-------------|
| `--primary` | Primary bibliography file |
| `--additional` | Additional bibliography file(s) |
| `--dedup-key` | Deduplication strategy (doi, title+author, key) |
| `--summary` | Path for merge report |

---

# Project Structure

```
.
├── scholar_static.py         # Download Google Scholar result pages to HTML
├── scholar_scraper.py        # Core scraping logic
├── scholar_bibtex.py         # BibTeX generation from scraped data
├── scholar_bibtex_pdf.py     # PDF metadata → BibTeX
├── get_biblio.py             # Enhanced PDF → BibTeX with DOI
├── merge_bib.py              # BibTeX merge & deduplication
├── merge_pdfs.py             # PDF batch merging utility
├── main.sh                   # End-to-end Google Scholar pages → validated PDFs
├── path/to/gs_run.sh         # Batch processing script
├── scholar_fup_pdfs.sh       # Download and validate candidate PDFs
├── requirements.txt          # Python dependencies
├── pages/                    # Input directory for batch HTML files
├── output/                   # Default output directory
├── pdf/                      # Downloaded, validated PDFs
├── merge_pdfs/               # Output directory for merged PDFs | source for Gemini notebooks
└── tests/                    # Sample HTML for testing
```

## Directory Conventions

| Directory | Purpose |
|-----------|---------|
| `pages/` | Place saved HTML files here for batch processing |
| `output/` | Default location for generated CSV/BibTeX files |
| `pdf/` | Destination for downloaded, validated PDFs |
| `pdf/` | Default location for PDF input files |
| `tests/` | Sample HTML files for testing parsers |

---

# Responsible Use Guidelines

1. **Respect `robots.txt`** – Google Scholar's `robots.txt` disallows scraping; use at your own risk
2. **Throttle Requests** – PDF requests are spaced by the configured `--delay`; avoid parallel runs
3. **Respect Access Controls** – The downloader follows ordinary HTTP redirects but does not bypass login, paywall, or bot challenges
4. **Use Official APIs** – For large-scale needs, prefer [Semantic Scholar API](https://api.semanticscholar.org/), [Crossref](https://www.crossref.org/), or [OpenAlex](https://openalex.org/)

---

# Troubleshooting

| Issue | Solution |
|-------|----------|
| **Rate limited (HTTP 429)** | Increase `--delay`, reduce concurrency, wait longer between runs |
| **Captcha while downloading** | Let the script restart in headful mode and solve it, or run with `--headful`; the solved session is reused via `--profile-dir` |
| **Empty results** | Check if HTML structure changed; update selectors in `extract_record_from_html` |
| **PDF parsing fails** | Ensure PDF is text-based (not scanned); try `pdftotext` manually |
| **Missing DOI** | Use `get_biblio.py` + manually fill `no-doi-found.csv` |
| **Encoding errors** | Ensure terminal uses UTF-8; add `# -*- coding: utf-8 -*-` to scripts |

---

# Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/improvement`)
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request with clear description

---

# License

MIT License – see `LICENSE` for details.

---

# Acknowledgments

- Built with `requests`, `BeautifulSoup`, `pypdf`
- Inspired by academic research workflows
- Thanks to the open-source community for parsing utilities
