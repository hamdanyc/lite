# Google Scholar Scraper

Scrape Google Scholar results to CSV, process saved pages in batches, or extract BibTeX metadata from PDFs.

## Setup

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

## Workflows

| Task | Command or input | Output |
| --- | --- | --- |
| Search by keyword | `python3 scholar_scraper.py --keyword "deep learning" --output output_data.csv` | CSV file |
| Search by URL | `python3 scholar_scraper.py --url "https://scholar.google.com/scholar?q=deep+learning" --output output_data.csv` | CSV file |
| Parse a saved page | `python3 scholar_scraper.py --html-file tests/sample_scholar_page.html --output sample_output.csv` | CSV file |
| Process saved pages | Put HTML files under `pages/`, then run `bash path/to/gs_run.sh` from the repository root | Per-page CSVs and `output/all_records.csv` |
| Extract PDF metadata | `python3 scholar_bibtex_pdf.py --pdfs-dir pdf/ --output from_pdfs.bib --limit 25` | BibTeX and `pdf_src.csv` |

The batch script searches `pages/` recursively and removes duplicate rows by title and authors. The PDF workflow also writes a cross-reference CSV mapping each PDF ID to its file and title.

## CSV fields

| Field | Contents |
| --- | --- |
| `Title` | Result title |
| `Authors` | Listed authors |
| `Abstract` | Result abstract |
| `Citation Details` | Citation information |
| `PDF_URL` | PDF link, when available |

## Responsible use

Requests include a throttling delay. Use the scraper carefully to avoid overloading Google Scholar.
