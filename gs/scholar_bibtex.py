from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from typing import Dict, Iterable, List, Tuple
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


def parse_citation(text: str) -> Tuple[str, str]:
    """Parse a citation text block to extract the year and publication name."""
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
    publication = _strip_gscholar_citation_markers(publication)
    return year, publication


def extract_cite_ids(html: str | BeautifulSoup, source_url: str) -> Tuple[str, str]:
    """Extract Google Scholar cite ID and cluster ID from a result row HTML."""
    if isinstance(html, str):
        soup = BeautifulSoup(html, "html.parser")
    elif hasattr(html, "select_one"):
        soup = html
    else:
        soup = BeautifulSoup(str(html), "html.parser")

    cite_id = ""
    cluster_id = ""

    # The title link often carries the cluster/scid parameters.
    title_link = soup.select_one(".gs_rt a.gs_rl, .gs_rt a.gs_title, .gs_rt a.gs_tr")
    if not title_link:
        title_link = soup.select_one(".gs_rt a")
    if title_link and title_link.get("href"):
        params = dict(re.findall(r"(\w+)=(\S+?)(?:&|$)", title_link["href"]))
        cluster_id = params.get("cluster") or params.get("scid") or ""

    # The "Cite" link inside .gs_a carries the cite=ID parameter.
    gs_a = soup.select_one(".gs_a")
    if gs_a:
        for a in gs_a.find_all("a"):
            href = a.get("href") or ""
            text = clean_text(a.get_text(" ", strip=True))
            if "cites=" in href and "cite" in text.lower():
                params = dict(re.findall(r"(\w+)=(\S+?)(?:&|$)", href))
                cite_id = params.get("cites") or ""
                break

    return cite_id, cluster_id


def fetch_citation_text(cite_id: str, cluster_id: str, session: requests.Session, timeout: float = 30.0) -> str | None:
    """Fetch the full citation (BibTeX/plain-text) for a record from Google Scholar's cite endpoint."""
    if not cite_id or not cluster_id:
        return None
    url = (
        f"https://scholar.googleusercontent.com/scholar.bib?"
        f"cluster={quote(cluster_id, safe='')}&hl=en&cites={quote(cite_id, safe='')}&num=10"
    )
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/plain,*/*",
    }
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            text = clean_text(response.text)
            if not text:
                continue
            if text.lstrip().startswith("@"):
                # Valid BibTeX entry.
                return text
            if re.search(r"\b(19|20)\d{2}\b", text) and ("doi" in text.lower() or "journal" in text.lower() or "@" in text):
                # Plain citation text that contains a year and citation markers.
                return text
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1)
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    if last_error:
        print(f"  Warning: failed to fetch citation (cite={cite_id[:10]} cluster={cluster_id[:10]}): {last_error}")
    return None


def _split_top_level(s: str) -> List[str]:
    """Split a BibTeX field list at commas that are not inside braces/quotes."""
    parts = []
    depth = 0
    in_string = False
    string_char: str | None = None
    start = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            if ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
        i += 1
    parts.append(s[start:].strip())
    return [p for p in parts if p]


def _extract_bibtex_value(part: str) -> Tuple[str, str]:
    """Parse a BibTeX field 'name = value' into (name, value)."""
    m = re.match(r"(\w+)\s*=\s*", part)
    if not m:
        return "", ""
    name = m.group(1).lower()
    rest = part[m.end():].strip()
    if rest.startswith("{"):
        depth = 0
        end = 0
        for i, ch in enumerate(rest):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        value = rest[1:end - 1]
    elif rest.startswith('"'):
        end = rest.find('"', 1)
        value = rest[1:end] if end != -1 else rest[1:]
    elif rest.startswith("#"):
        # Ignore BibTeX concatenation expressions for robustness.
        value = ""
    else:
        value = rest
    return name, value


def parse_bibtex_record(text: str) -> Dict[str, str]:
    """Parse a BibTeX entry into structured fields."""
    result: Dict[str, str] = {"authors": [], "title": "", "journal": "", "year": "",
                               "volume": "", "number": "", "pages": "", "doi": "", "url": "", "eprint": ""}
    m = re.search(r"@(\w+)\s*\{\s*([^,]+),\s*(.*?)\s*\}\s*$", text, re.S | re.I)
    if not m:
        return result
    block = m.group(3)
    for part in _split_top_level(block):
        name, value = _extract_bibtex_value(part)
        if not name:
            continue
        value = clean_text(value.replace("\\", "")).strip()
        if name == "author":
            result["authors"] = [a.strip() for a in value.split(" and ") if a.strip()]
        elif name == "title":
            result["title"] = value
        elif name == "journal" or name == "journaltitle":
            result["journal"] = value
        elif name == "year":
            y = re.sub(r"\D", "", value)
            result["year"] = y if y else value
        elif name == "volume":
            result["volume"] = value
        elif name == "number" or name == "issue":
            result["number"] = value
        elif name == "pages":
            result["pages"] = value
        elif name == "doi":
            result["doi"] = value
        elif name == "url":
            result["url"] = value
        elif name == "eprint" or name == "primary":
            result["eprint"] = value
        elif name == "publisher":
            result["publisher"] = value
        elif name == "abstract":
            result["abstract"] = value
    return result


def parse_apa_citation(text: str) -> Dict[str, str]:
    """Best-effort parse of an APA-style plain-text citation."""
    result: Dict[str, str] = {"authors": [], "title": "", "journal": "", "year": "",
                               "volume": "", "number": "", "pages": "", "doi": "", "url": "", "eprint": ""}
    line = clean_text(text)
    if not line:
        return result

    # Extract DOI (plain, dx.doi.org, or https URL variants).
    doi_match = re.search(r"doi[:.]?\s*(\S+)|dx\.doi\.org/(\S+)|\bhttps?://\S+doi\w*\/?\S*", line, re.I)
    if doi_match:
        result["doi"] = clean_text(doi_match.group(0) or doi_match.group(1) or "")

    # Extract arXiv ID (e.g., arXiv:2408.13296, arXiv:2408.13296v1, or 2408.13296).
    arxiv_match = re.search(
        r"\b(arxiv[:.\s-]+)?\s*(\d{4}\.\d{4,}(?:v\d+)?)(?!\d)",
        line,
        re.I,
    )
    if arxiv_match:
        # Prefer the normalized form "arXiv:2408.13296".
        arxiv = arxiv_match.group(0).strip()
        result["eprint"] = clean_text(arxiv)

    if not result["doi"]:
        url_match = re.search(r"https?://\S+", line)
        if url_match:
            result["url"] = clean_text(url_match.group(0))

    year_match = re.search(r"\((\d{4})\)\s*\.?\s*([^.,])", line)
    if year_match:
        result["year"] = year_match.group(1)
        body = line[year_match.end():].strip()
    else:
        body = re.sub(r"\s*\(\d{4}\)\s*", " ", line)

    first_period = body.find(".")
    if first_period != -1:
        authors_str = body[:first_period].strip()
        body = body[first_period + 1:].strip()
        authors_str = re.sub(r"\s+(?:and|&|,\s*and)\s+", "; ", authors_str, flags=re.I)
        result["authors"] = [a.strip() for a in authors_str.split("; ") if a.strip()]

    title_match = re.match(r"^(?:\"|')?(.+?)(?:\"|')?\.\s*$", body, re.S | re.I)
    if title_match:
        result["title"] = clean_text(title_match.group(1))
        rest = body[title_match.end():].strip()
    else:
        rest = body

    journal_match = re.match(r"^([^,]+),", rest)
    if journal_match:
        result["journal"] = clean_text(journal_match.group(1))
        rest = rest[journal_match.end():].strip()

    vol_match = re.search(r"vol\.?\s*(\d+)", rest, re.I)
    if vol_match:
        result["volume"] = vol_match.group(1)
        rest = rest[vol_match.end():].strip()

    num_match = re.search(r"no\.?\s*(\d+)|\((\d+)\)", rest, re.I)
    if num_match:
        result["number"] = clean_text(num_match.group(1) or num_match.group(2) or "")
        rest = rest[num_match.end():].strip()

    pp_match = re.search(r"pp\.?\s*([^-]+)", rest, re.I) or re.search(r"pp?\.\s*([^.]+)", rest, re.I)
    if pp_match:
        result["pages"] = clean_text(pp_match.group(1)).rstrip(".,")

    return result


def parse_citation_content(raw: str) -> Dict[str, str]:
    raw = clean_text(raw)
    if not raw:
        return {}
    if raw.lstrip().startswith("@"):
        return parse_bibtex_record(raw)
    return parse_apa_citation(raw)


def extract_inline_citations(soup: BeautifulSoup) -> List[str]:
    """Extract citation text blocks from inline Google Scholar cite dialog content."""
    blocks = []
    for el in soup.select(".gsc_cit, .gs_cit"):
        text = clean_text(el.get_text(" ", strip=True))
        if not text or len(text) < 30:
            continue
        if re.search(r"\b(19|20)\d{2}\b", text):
            blocks.append(text)
    return blocks[:20]


def _strip_gscholar_citation_markers(text: str) -> str:
    """Remove Google Scholar citation markup such as '[HTML]', '[PDF]', '[BIBTEX]', '[EXPORT]', '[CITATION]'.

    This is applied aggressively to titles, abstracts, publication and citation details,
    and any free-text field before they are written into the BibTeX output.
    """
    if not text:
        return ""
    # Remove bracketed citation markers anywhere in the text.
    text = re.sub(r"\s*\[\s*(HTML|PDF|BIBTEX|EXPORT|CITATION|citation)\s*\]\s*", " ", text, flags=re.I)
    return clean_text(text)


def _merge_citation(record: Dict[str, str], cit: Dict[str, str]) -> None:
    """Merge citation-parsed fields into a record (citation data is the primary source)."""
    if cit.get("authors"):
        record["authors"] = [format_author_for_bibtex(a) for a in cit["authors"]]
    if cit.get("title"):
        record["title"] = cit["title"]
    if cit.get("journal"):
        record["publication"] = cit["journal"]
    if cit.get("year"):
        record["year"] = re.sub(r"\D", "", cit["year"])
    if cit.get("volume"):
        record["volume"] = cit["volume"]
    if cit.get("number"):
        record["number"] = cit["number"]
    if cit.get("pages"):
        record["pages"] = cit["pages"]
    if cit.get("doi"):
        record["doi"] = cit["doi"]
    if cit.get("url"):
        record["doi_url"] = cit["url"]
    if cit.get("publisher"):
        record["publisher"] = cit["publisher"]
    if cit.get("eprint"):
        record["eprint"] = cit["eprint"]
    if not record.get("abstract") and cit.get("abstract"):
        record["abstract"] = clean_text(cit["abstract"])


def format_author_for_bibtex(full_name: str) -> str:
    """Format a name as 'LastName, FirstName' for BibTeX author field."""
    name = clean_text(full_name)
    if not name:
        return ""
    if ", " in name:
        parts = [p.strip() for p in name.split(",", 1)]
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ""
        return f"{last}, {first}"
    parts = name.rsplit(" ", 1)
    if len(parts) == 2:
        return f"{parts[1]}, {parts[0]}"
    return name


def sanitize_bibtex_field(text: str) -> str:
    """Escape braces, ampersands, backslashes for BibTeX field values."""
    text = clean_text(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("&", "\\&")
    return text


def make_bibtex_key(rec_id: int) -> str:
    """Build a BibTeX citation key as a running ID: gs#1, gs#2, ..."""
    return f"gs#{rec_id}"


def enrich_record(record: Dict[str, str], source_url: str) -> Dict[str, str]:
    """Normalize and enrich a scraped record for BibTeX output."""
    clean: Dict[str, str] = {}
    clean["title"] = sanitize_bibtex_field(record.get("title", ""))
    clean["authors"] = [
        sanitize_bibtex_field(format_author_for_bibtex(a))
        for a in record.get("authors", [])
    ]
    clean["year"] = clean_text(str(record.get("year", "")))
    clean["publication"] = sanitize_bibtex_field(record.get("publication", ""))
    clean["abstract"] = sanitize_bibtex_field(record.get("abstract", ""))
    clean["citation_details"] = sanitize_bibtex_field(record.get("citation_details", ""))
    clean["pdf_url"] = normalize_url(record.get("pdf_url", "") or source_url)
    clean["volume"] = clean_text(str(record.get("volume", "")))
    clean["number"] = clean_text(str(record.get("number", "")))
    clean["pages"] = clean_text(str(record.get("pages", "")))
    clean["doi"] = sanitize_bibtex_field(record.get("doi", ""))
    clean["doi_url"] = sanitize_bibtex_field(record.get("doi_url", ""))
    clean["publisher"] = sanitize_bibtex_field(record.get("publisher", ""))
    clean["eprint"] = sanitize_bibtex_field(record.get("eprint", ""))

    if " - " in clean["citation_details"]:
        parts = [p.strip() for p in clean["citation_details"].split(" - ", 1)]
        clean["publisher"] = sanitize_bibtex_field(parts[-1]) if len(parts) > 1 else ""
        if not clean["publication"]:
            clean["publication"] = sanitize_bibtex_field(parts[0])

    if not clean["authors"]:
        author_text = clean["citation_details"] if clean["citation_details"] else clean["publication"]
        clean["authors"] = [
            sanitize_bibtex_field(format_author_for_bibtex(a))
            for a in parse_authors(author_text)
        ]
        clean["authors"] = [a for a in clean["authors"] if a]

    return clean


def _parse_page_records(html: str | BeautifulSoup, source_url: str, keyword: str, progress: bool) -> List[dict]:
    """Parse records from a single page's soup (returns list of record dicts with cite IDs attached)."""
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "html.parser")
    items = soup.select("div.gs_r, div.gs_ri, .gs_or, .gs_gg")

    records: List[dict] = []
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
        cite_id, cluster_id = extract_cite_ids(item, source_url)
        record["_cite_id"] = cite_id
        record["_cluster_id"] = cluster_id
        records.append(record)
    return records


def parse_html_records(
    html_sources: List[Tuple[str | BeautifulSoup, str]],
    keyword: str = "",
    progress: bool = True,
    citation_timeout: float = 30.0,
    citations_limit: int = 200,
) -> List[dict]:
    """Parse all records from one or more Google Scholar HTML pages/soups.

    html_sources: list of (html_string_or_soup, source_url) tuples.
    citations_limit: maximum number of records that get their citation data
                     fetched from Google Scholar's cite endpoint.
                     This throttles API calls; all parsed records are still
                     returned regardless of this cap.
    """
    parsed_records: List[dict] = []
    page_inline: List[List[str]] = []

    for html, source_url in html_sources:
        soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "html.parser")
        inline = extract_inline_citations(soup) if ("cites=" in source_url or "cluster=" in source_url) else []
        page_inline.append(inline)
        parsed_records.extend(_parse_page_records(html, source_url, keyword, progress))

    # Fetch rich citation data (publication, DOI, pages, volume, issue, URL, eprint, etc.) from Google
    # Scholar's dedicated 'cite' endpoint, using each record's cluster and cite IDs.
    cite_tqdm = tqdm(
        enumerate(parsed_records), disable=not progress,
        desc="Fetching citation data", unit="rec",
    )
    cite_idx = 0
    session: requests.Session | None = None
    for idx, record in cite_tqdm:
        if idx >= citations_limit:
            break
        cite_id = record.get("_cite_id", "")
        cluster_id = record.get("_cluster_id", "")
        if not cite_id or not cluster_id:
            continue
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)
        raw = fetch_citation_text(cite_id, cluster_id, session, timeout=citation_timeout)
        if raw:
            cit = parse_citation_content(raw)
            _merge_citation(record, cit)
        else:
            # Fallback to inline citation text for this record.
            page_idx = idx
            while page_idx >= len(page_inline):
                page_idx -= len(page_inline)
            if page_idx < len(page_inline) and cite_idx < len(page_inline[page_idx]):
                cit = parse_citation_content(_strip_gscholar_citation_markers(page_inline[page_idx][cite_idx]))
                _merge_citation(record, cit)
                cite_idx += 1
    return parsed_records


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
            "Using a browser-assisted fallback or a saved HTML file with --url/--html-file/--pages-dir is recommended. "
            f"Blocked URL: {url}"
        )
        return []

    return parse_html_records([(html, url)], keyword=keyword, progress=progress)


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


def entry_type(record: Dict[str, str]) -> str:
    if record.get("eprint"):
        return "misc"
    if record.get("publication"):
        return "article"
    if record.get("publisher"):
        return "inbook"
    if record.get("pdf_url"):
        return "misc"
    return "misc"


def record_to_bibtex(rec_id: int, record: Dict[str, str]) -> str:
    """Format a record as an APA-style BibTeX entry with a running ID key."""
    rec_key = make_bibtex_key(rec_id)
    pub = record.get("publication") or record.get("publisher") or ""
    doi = record.get("doi") or record.get("doi_url") or ""
    pdf_url = record.get("pdf_url", "")
    year = record.get("year", "")
    eprint = record.get("eprint", "")

    atype = entry_type(record)
    if not pub and not pdf_url:
        atype = "misc"

    lines = [f"@{atype}{{{rec_key},"]

    authors = record.get("authors", [])
    if authors:
        lines.append("  author = {" + " and ".join(authors) + "},")

    if record.get("title"):
        lines.append(f"  title = {{{record['title']}}},")

    if pub:
        if atype == "article":
            lines.append(f"  journal = {{{pub}}},")
        else:
            lines.append(f"  publisher = {{{pub}}},")

    if year:
        lines.append(f"  year = {year},")

    if record.get("volume"):
        lines.append(f"  volume = {{{record['volume']}}},")
    if record.get("number"):
        lines.append(f"  number = {{{record['number']}}},")
    if record.get("pages"):
        lines.append(f"  pages = {{{record['pages']}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    if eprint:
        lines.append(f"  eprint = {{{eprint}}},")

    cite_urls = [doi, pdf_url]
    if record.get("doi_url") and record["doi_url"] not in cite_urls:
        cite_urls.append(record["doi_url"])
    link = next((u for u in cite_urls if u), "")
    if link:
        lines.append(f"  url = {{{link}}},")

    note_parts: List[str] = []
    if record.get("abstract"):
        abs_preview = record["abstract"][:150]
        if len(record["abstract"]) > 150:
            abs_preview += "..."
        note_parts.append(f"Abstract: {abs_preview}")
    if record.get("citation_details"):
        note_parts.append(f"Source: {record['citation_details']}")

    if note_parts:
        lines.append("  note = {" + "; ".join(note_parts) + "},")

    lines.append("}")
    return "\n".join(lines) + "\n"


def write_bibtex(records: Iterable[Dict[str, str]], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        handle.write("@string{scholar-tool = \"scholar_bibtex\"}\n\n")
        for rec_id, record in enumerate(records, start=1):
            handle.write(record_to_bibtex(rec_id, record))


def write_pdf_csv(pdf_records: Iterable[Tuple[int, Dict[str, str]]], output_path: str) -> None:
    """Write a CSV containing the ID, title and PDF URL for records with a PDF link."""
    fieldnames = ["ID", "Title", "PDF_URL"]
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for rec_id, record in pdf_records:
            writer.writerow(
                {
                    "ID": rec_id,
                    "Title": record.get("title", ""),
                    "PDF_URL": record.get("pdf_url", ""),
                }
            )


def _derive_base_url(args, path: str, html: str) -> str:
    """Derive a sensible base URL from the page itself or from the file/args."""
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
        stem = os.path.splitext(os.path.basename(path))[0]
        if args.keyword:
            query = quote(" ".join(args.keyword), safe="")
        elif args.keywords:
            query = quote(args.keywords.replace(",", " "), safe="")
        else:
            query = quote(stem, safe="")
        base_url = f"https://scholar.google.com/scholar?q={query}&hl=en"
    return base_url


def _collect_html_files(page_dir: str) -> List[str]:
    """Collect all HTML files from the given directory (sorted for deterministic processing)."""
    files = []
    for root, _, filenames in os.walk(page_dir):
        for filename in filenames:
            if filename.lower().endswith((".html", ".htm", ".xhtml")):
                files.append(os.path.join(root, filename))
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape research records from Google Scholar pages and export as APA-style BibTeX."
    )
    parser.add_argument("--keyword", action="append", default=[], help="Keyword to search for. Repeatable.")
    parser.add_argument("--keywords", help="Comma-separated keyword list.")
    parser.add_argument("--url", help="Direct URL to scrape instead of querying a search page.")
    parser.add_argument("--html-file", help="Path to a single local HTML file to parse for testing.")
    parser.add_argument(
        "--pages-dir",
        help="Path to a folder containing HTML files to iterate over as input (all .html files read).",
    )
    parser.add_argument("--limit", type=int, default=10000, help="Maximum number of records to export (set 0 for no limit).")
    parser.add_argument("--output", default="output_bibtex.bib", help="Path to the BibTeX file to write.")
    parser.add_argument("--pdf-output", default="pdf.csv", help="Path to the CSV file to write for PDF URLs (set empty to disable).")
    parser.add_argument("--delay", type=float, default=7.0, help="Delay in seconds between requests.")
    parser.add_argument(
        "--citation-timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for fetching per-record citation data from the cite endpoint.",
    )
    parser.add_argument(
        "--citations-limit",
        type=int,
        default=200,
        help="Maximum number of records whose citation data is fetched from the cite endpoint (throttles API calls).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars for non-interactive or quiet environments.",
    )
    args = parser.parse_args()

    keywords = list(args.keyword)
    if args.keywords:
        keywords.extend(part.strip() for part in args.keywords.split(",") if part.strip())
    if not keywords and not args.url and not args.html_file and not args.pages_dir:
        keywords = ["deep learning", "natural language processing"]

    progress_enabled = not args.no_progress and sys.stderr.isatty()

    pages_dir = args.pages_dir

    if args.html_file and pages_dir:
        print("Error: --html-file and --pages-dir are mutually exclusive.")
        sys.exit(1)

    if args.url:
        records = fetch_records_from_url(
            args.url,
            keyword="",
            delay_seconds=args.delay,
            progress=progress_enabled,
        )
    elif pages_dir:
        html_files = _collect_html_files(pages_dir)
        if not html_files:
            print(f"No HTML files found in {pages_dir}.")
            sys.exit(1)
        if progress_enabled:
            print(f"Reading {len(html_files)} HTML file(s) from {pages_dir}")
        html_sources: List[Tuple[str, str]] = []
        for path in tqdm(html_files, disable=not progress_enabled, desc="Reading pages", unit="file"):
            with open(path, "r", encoding="utf-8") as handle:
                html = handle.read()
            if not args.url and not args.html_file:
                base_url = _derive_base_url(args, path, html)
            else:
                base_url = args.url or "https://scholar.google.com/scholar"
            html_sources.append((html, base_url))
        records = parse_html_records(
            html_sources,
            keyword="",
            progress=progress_enabled,
            citation_timeout=args.citation_timeout,
            citations_limit=args.citations_limit,
        )
    elif args.html_file:
        with open(args.html_file, "r", encoding="utf-8") as handle:
            html = handle.read()
        base_url = _derive_base_url(args, args.html_file, html)
        records = parse_html_records(
            [(html, base_url)],
            keyword="",
            progress=progress_enabled,
            citation_timeout=args.citation_timeout,
            citations_limit=args.citations_limit,
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

    limit = args.limit
    final_records = filtered[: (limit if limit > 0 else len(filtered))]

    if args.pdf_output:
        pdf_records = [(rec_id + 1, rec) for rec_id, rec in enumerate(final_records) if rec.get("pdf_url", "").endswith(".pdf")]
        write_pdf_csv(pdf_records, args.pdf_output)

    # Write BibTeX with running IDs (gs#1, gs#2, ...) to the requested output path.
    write_bibtex(final_records, args.output)
    print(f"Parsed {len(filtered)} unique records. Exported {len(final_records)} records (limit {limit}). Saved to {args.output}.")
    if args.pdf_output:
        print(f"Extracted {len(pdf_records)} PDF URLs. Saved to {args.pdf_output}.")


if __name__ == "__main__":
    main()
