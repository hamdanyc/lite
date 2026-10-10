from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from typing import Iterable, List
from urllib.parse import quote, urljoin, urlencode

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - optional browser fallback
    sync_playwright = None

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    def tqdm(iterable=None, *args, **kwargs):
        return iterable if iterable is not None else []


def browser_fetch_html(url: str, wait_seconds: float = 10.0) -> str:
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed. Install it with: python -m pip install playwright")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 2200},
        )
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        content = page.content()
        browser.close()

    if "sorry/index" in page.url.lower() or "captcha" in content.lower():
        raise GoogleScholarRateLimitError(f"Google Scholar blocked the browser-assisted request for {url}")

    return content


class GoogleScholarRateLimitError(RuntimeError):
    """Raised when Google Scholar refuses additional requests."""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\xa0", " ").split()).strip()


def normalize_url(raw_url: str | None, base_url: str = "") -> str:
    if not raw_url:
        return ""
    url = raw_url.strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(base_url or "https://scholar.google.com", url)
    return url


def parse_authors(author_block: str) -> List[str]:
    text = clean_text(author_block)
    if not text:
        return []
    text = text.replace(";", ",")
    text = re.sub(r"\s+\b(?:and|& )\b\s+", ", ", text, flags=re.IGNORECASE)
    authors = [part.strip() for part in re.split(r"\s*,\s*", text) if part.strip()]
    if len(authors) == 1:
        return authors
    return authors


def extract_year_from_text(text: str) -> str:
    match = re.search(r"\b(?:19|20)\d{2}\b", text)
    return match.group(0) if match else ""


def parse_citation(text: str) -> tuple[str, str]:
    """Parse a citation text block to extract the year and publication name.

    Google Scholar citation blocks usually follow the form:
        "Author A, Author B - 2021 - Journal Name - Publisher - ..."
    """
    text = clean_text(text)
    if not text:
        return "", ""
    parts = [p.strip() for p in re.split(r"\s+-\s+", text) if p.strip()]

    year = ""
    publication = ""
    for i, part in enumerate(parts):
        y = extract_year_from_text(part)
        if y and not year:
            year = y
            if i + 1 < len(parts):
                publication = clean_text(" - ".join(parts[i + 1:]))
            break

    return year, publication


def find_pdf_url(soup: BeautifulSoup, source_url: str) -> str:
    if source_url.lower().endswith(".pdf"):
        return source_url
    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        txt = clean_text(anchor.get_text(" ", strip=True))
        if ".pdf" in href.lower() or ".pdf" in txt.lower():
            return normalize_url(href, source_url)
        if "download" in href.lower():
            return normalize_url(href, source_url)
    return ""


def extract_record_from_html(html: str | BeautifulSoup, source_url: str) -> dict:
    if isinstance(html, str):
        soup = BeautifulSoup(html, "html.parser")
    elif hasattr(html, "select_one"):
        soup = html
    else:
        soup = BeautifulSoup(str(html), "html.parser")

    # Title: prefer link inside gs_rt, else gs_rt/td.gs_tde itself, fallback to first title-like link.
    title_tag = soup.select_one(
        ".gs_rt a, .gs_rt, td.gs_tde, td.gs_tde a, a.gs_rt"
    )
    if not title_tag:
        for a in soup.select("a"):
            t = clean_text(a.get_text(" ", strip=True))
            if t and len(t) < 500:
                title_tag = a
                break

    title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")

    # Authors
    author_block = soup.select_one(".gs_a, td.gs_tde, div.gs_cits")
    author_text = clean_text(author_block.get_text(" ", strip=True) if author_block else "")
    if " - " in author_text:
        author_text, citation_text = author_text.split(" - ", 1)
    else:
        citation_text = author_text
        author_text = ""
    authors = parse_authors(author_text)

    # Abstract
    abstract_tag = soup.select_one(
        ".gs_rs, .gs_ab_md, .gs_ab, .gs_md, .gs_ri .gs_ab, .gs_rt"
    )
    abstract = clean_text(abstract_tag.get_text(" ", strip=True) if abstract_tag else "")

    # Citation details / year / publication
    year_tag = soup.select_one(".gs_cit, .gs_fl, div.gs_cits")
    year_text = clean_text(year_tag.get_text(" ", strip=True) if year_tag else "")
    citation_year, publication = parse_citation(citation_text)
    if not citation_year:
        citation_year = (
            extract_year_from_text(citation_text)
            or extract_year_from_text(year_text)
            or extract_year_from_text(abstract)
            or ""
        )
    if not publication:
        publication = citation_text

    citation_details = publication if publication else citation_year

    pdf_url = find_pdf_url(soup, source_url)

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "publication": publication,
        "year": citation_year,
        "citation_details": citation_details,
        "pdf_url": pdf_url,
    }


def parse_html_records(html: str | BeautifulSoup, source_url: str, keyword: str = "", progress: bool = True) -> List[dict]:
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "html.parser")
    records: List[dict] = []
    # Match all plausible Google Scholar result-row wrappers across markup versions.
    items = soup.select("div.gs_r, div.gs_ri, .gs_or, .gs_gg")

    for item in tqdm(items, disable=not progress, desc="Parsing results", unit="item"):
        record = extract_record_from_html(item, source_url)
        if not record["title"]:
            continue
        if keyword and keyword.lower() not in " ".join(
            [
                record["title"],
                record["abstract"],
                record.get("publication", ""),
                record.get("year", ""),
            ]
        ).lower():
            continue
        records.append(record)

    return records


def fetch_html(
    url: str,
    delay_seconds: float = 0.0,
    session: requests.Session | None = None,
    max_retries: int = 3,
) -> str:
    client = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        try:
            response = client.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            if response.status_code == 429 or "sorry/index" in response.url.lower():
                raise GoogleScholarRateLimitError(
                    f"Google Scholar rate-limited the request for {url}"
                )
            response.raise_for_status()
            if "sorry/index" in response.text.lower() or "captcha" in response.text.lower():
                raise GoogleScholarRateLimitError(
                    f"Google Scholar blocked the request for {url}"
                )
            return response.text
        except (requests.RequestException, GoogleScholarRateLimitError) as exc:
            last_error = exc
            try:
                browser_html = browser_fetch_html(url, wait_seconds=5)
                return browser_html
            except Exception:
                pass
            if attempt == max_retries:
                break
            time.sleep(min(2 ** attempt, 30))

    if last_error is not None:
        raise GoogleScholarRateLimitError(str(last_error)) from last_error
    raise GoogleScholarRateLimitError(f"Unable to fetch {url}")


def build_search_url(keyword: str) -> str:
    params = {
        "q": keyword,
        "hl": "en",
        "as_sdt": "0,5",
    }
    return "https://scholar.google.com/scholar?" + urlencode(params)


def fetch_records_from_url(
    url: str,
    keyword: str,
    delay_seconds: float = 7.0,
    progress: bool = True,
) -> List[dict]:
    session = requests.Session()
    try:
        html = fetch_html(url, delay_seconds=delay_seconds, session=session)
    except GoogleScholarRateLimitError as exc:
        print(
            "Google Scholar is rate-limiting automated requests from this environment. "
            "Using a browser-assisted fallback or a saved HTML file with --url/--html-file is recommended. "
            f"Blocked URL: {url}"
        )
        return []

    return parse_html_records(html, url, keyword=keyword, progress=progress)


def write_csv(records: Iterable[dict], output_path: str) -> None:
    fieldnames = ["Title", "Authors", "Abstract", "Publication", "Year", "Citation Details", "PDF_URL"]
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "Title": record.get("title", ""),
                    "Authors": "; ".join(record.get("authors", [])),
                    "Abstract": record.get("abstract", ""),
                    "Publication": record.get("publication", ""),
                    "Year": record.get("year", ""),
                    "Citation Details": record.get("citation_details", ""),
                    "PDF_URL": record.get("pdf_url", ""),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape research records from Google Scholar pages.")
    parser.add_argument("--keyword", action="append", default=[], help="Keyword to search for. Repeatable.")
    parser.add_argument("--keywords", help="Comma-separated keyword list.")
    parser.add_argument("--url", help="Direct URL to scrape instead of querying a search page.")
    parser.add_argument("--html-file", help="Path to a local HTML file to parse for testing.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum number of records to export.")
    parser.add_argument("--output", default="output_data.csv", help="Path to the CSV file to write.")
    parser.add_argument("--delay", type=float, default=7.0, help="Delay in seconds between requests.")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars for non-interactive or quiet environments.",
    )
    args = parser.parse_args()

    keywords = list(args.keyword)
    if args.keywords:
        keywords.extend(part.strip() for part in args.keywords.split(",") if part.strip())
    if not keywords and not args.url and not args.html_file:
        keywords = ["deep learning", "natural language processing"]

    progress_enabled = not args.no_progress and sys.stderr.isatty()

    if args.html_file:
        with open(args.html_file, "r", encoding="utf-8") as handle:
            html = handle.read()
        # Derive a sensible base URL from the page itself so relative links (e.g., PDFs) resolve.
        page_soup = BeautifulSoup(html, "html.parser")
        base_url = None
        base_tag = page_soup.find("base", href=True)
        if base_tag:
            base_url = base_tag["href"]
        if not base_url:
            og = page_soup.find("meta", property="og:url", attrs={"content": True})
            if og:
                base_url = og["content"]
        if not base_url:
            stem = os.path.splitext(os.path.basename(args.html_file))[0]
            base_url = f"https://scholar.google.com/scholar?q={quote(stem)}&hl=en"

        records = parse_html_records(
            html,
            source_url=base_url,
            keyword="",
            progress=progress_enabled,
        )
    elif args.url:
        records = fetch_records_from_url(
            args.url,
            keyword="",
            delay_seconds=args.delay,
            progress=progress_enabled,
        )
    else:
        records: List[dict] = []
        for keyword in tqdm(keywords[:5], disable=not progress_enabled, desc="Search keywords", unit="query"):
            url = build_search_url(keyword)
            try:
                records.extend(
                    fetch_records_from_url(
                        url,
                        keyword,
                        delay_seconds=args.delay,
                        progress=progress_enabled,
                    )
                )
            except GoogleScholarRateLimitError as exc:
                print(f"Search aborted for '{keyword}': {exc}")

    filtered = []
    seen = set()
    for record in records:
        title = record.get("title", "")
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(record)

    final_records = filtered[: max(args.limit, 0)]
    write_csv(final_records, args.output)
    print(f"Scraped {len(final_records)} records. Saved to {args.output}.")


if __name__ == "__main__":
    main()
