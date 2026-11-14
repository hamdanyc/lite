# Google Scholar Scraper & BibTeX Toolkit

A comprehensive toolkit for scraping Google Scholar, extracting bibliographic metadata from PDFs, and managing BibTeX libraries. Designed for researchers who need to collect, organize, and export academic references efficiently.

## Features

- **Google Scholar Scraping** – Parse saved HTML pages and batch-process directories of saved pages
- **BibTeX Generation** – Convert scraped records or PDF metadata into valid BibTeX entries
- **PDF Metadata Extraction** – Parse title, authors, year, abstract, and DOI from PDF files
- **BibTeX Management** – Merge, deduplicate, and summarize BibTeX libraries
- **Responsible Scraping** – Built-in throttling, retry logic, and rate-limit handling

---

# Workflows

## 1. Scrape Google Scholar

| Method | Description | Output |
|--------|-------------|--------|
| **Parse saved HTML** | Process one locally saved Google Scholar results page | CSV, `output/fup_pdf.txt`, and any accessible PDFs |
| **Batch process** | Recursively scan `pages/` and merge records | `output/all_records.csv` + per-page CSVs |

For a single page, run the scraper and then the candidate downloader:

```bash
python3 scholar_scraper.py --html-file pages/ml_5.html --output output/output_ml_5.csv --no-progress
bash download_fup_pdfs.sh
```

The scraper writes distinct candidate links to `output/fup_pdf.txt` and attempts to download valid, accessible PDFs to `articles/pdf-N.pdf`. `download_fup_pdfs.sh` retries the URLs in that list, validates each response with `pdfinfo`, and continues numbering after the highest existing `pdf-N.pdf`. It requires `curl` and `pdfinfo` (provided by `poppler-utils` on Debian/Ubuntu). HTML error pages, blocked responses, and invalid PDFs are discarded.

**Batch processing (`path/to/gs_run.sh`)** recursively scans `pages/`, extracts records from each HTML file, and merges them into `output/all_records.csv` with deduplication by title and authors. Since each scraper invocation rewrites `output/fup_pdf.txt`, after a batch run that file contains candidates from the last processed HTML page only.

## 2. Generate BibTeX from Scraped Data

```bash
# Basic conversion
python3 scholar_bibtex.py --input scraped_data.csv --output library.bib

# With options
python3 scholar_bibtex.py --input data.csv --output library.bib --limit 100 --delay 5.0
```

## 3. Extract Metadata from PDFs

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

## 4. Manage BibTeX Libraries

```bash
# Merge two BibTeX files with deduplication and summary
python3 merge_bib.py --primary main.bib --additional new.bib --output merged.bib --summary merge_report.txt
```

**Merge features:**
- Deduplicates by DOI, title+authors, or BibTeX key
- Preserves the most complete record
- Generates a CRUD summary (Created, Retained, Updated, Deleted)

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
├── scholar_scraper.py        # Core scraping logic
├── scholar_bibtex.py         # BibTeX generation from scraped data
├── scholar_bibtex_pdf.py     # PDF metadata → BibTeX
├── get_biblio.py             # Enhanced PDF → BibTeX with DOI
├── merge_bib.py              # BibTeX merge & deduplication
├── path/to/gs_run.sh         # Batch processing script
├── download_fup_pdfs.sh      # Download and validate candidate PDFs
├── requirements.txt          # Python dependencies
├── pages/                    # Input directory for batch HTML files
├── output/                   # Default output directory
├── articles/                 # Downloaded, validated PDFs
├── pdf/                      # Default PDF input directory
└── tests/                    # Sample HTML for testing
```

## Directory Conventions

| Directory | Purpose |
|-----------|---------|
| `pages/` | Place saved HTML files here for batch processing |
| `output/` | Default location for generated CSV/BibTeX files |
| `articles/` | Destination for downloaded, validated PDFs |
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
