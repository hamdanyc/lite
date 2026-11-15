"""Download static HTML pages from Google Scholar for a given query.

Example:
    python scholar_static.py --query "machine learning survey" --pages 25

Google Scholar aggressively rate-limits plain HTTP clients (HTTP 429 / captcha),
so by default this script drives a real headless Chrome browser via Selenium.
If Selenium is not installed (or ``--no-browser`` is passed) it falls back to
plain ``requests``.

If Google Scholar serves a captcha while running headless, the script
automatically restarts the browser in headful mode so you can solve it; the
solved session is stored in the persistent profile directory
(``--profile-dir``) and reused by later runs.
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import random
import re
import sys
import time
from pathlib import Path

import requests

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    class _DummyBar:
        """Minimal stand-in for a tqdm progress bar.

        Supports both usage patterns:
          * ``tqdm(iterable)``      -> iterable that updates as it is consumed
          * ``tqdm(total=..., ...)`` -> context manager with ``update``/``close``
        """

        def __init__(self, iterable=None, total=None):
            self.iterable = iterable
            self.total = total
            self.n = 0

        def update(self, n=1):
            self.n += n

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

        def __iter__(self):
            if self.iterable is None:
                return
            for item in self.iterable:
                yield item
                self.update(1)

    def tqdm(iterable=None, *args, **kwargs):
        return _DummyBar(iterable=iterable, total=kwargs.get("total"))


try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    SELENIUM_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - selenium is optional
    SELENIUM_AVAILABLE = False

    class WebDriverException(Exception):  # type: ignore[no-redef]
        """Placeholder used when selenium is not installed."""

    class TimeoutException(Exception):  # type: ignore[no-redef]
        """Placeholder used when selenium is not installed."""


logger = logging.getLogger(__name__)


SCHOLAR_BASE_URL = "https://scholar.google.com/scholar"
RESULTS_PER_PAGE = 10
DEFAULT_OUTPUT_DIR = "pages"
DEFAULT_PROFILE_DIR = ".chrome-profile"
DEFAULT_DELAY_SECONDS = 7.0
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_WAIT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_CAPTCHA_WAIT_SECONDS = 180.0
DEFAULT_YEAR_FROM = 2024

CHROME_VERSION = "122.0.0.0"


def _default_user_agent() -> str:
    """Return a Chrome User-Agent that matches the current platform.

    A Windows UA on a Linux host (or vice versa) is a strong bot signal, so we
    derive the UA from the actual OS instead of hard-coding one.
    """
    system = platform.system()
    if system == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{CHROME_VERSION} Safari/537.36"
        )
    if system == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{CHROME_VERSION} Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_VERSION} Safari/537.36"
    )


DEFAULT_HEADERS = {
    "User-Agent": _default_user_agent(),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Injected into every page before any other script runs, to hide the most
# common headless-Chrome fingerprints.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
"""


class GoogleScholarRateLimitError(RuntimeError):
    """Raised when Google Scholar responds with a rate-limit / captcha page."""


def slugify(value: str) -> str:
    """Turn an arbitrary query string into a filesystem-friendly slug."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "query"


def build_search_url(
    query: str,
    page: int,
    year_from: int | None = None,
) -> str:
    """Build a Google Scholar search URL for the given query and page number.

    Page numbering is 1-based; page 1 corresponds to ``start=0``.

    If ``year_from`` is provided, results are restricted to that publication
    year and later via Google Scholar's ``as_ylo`` (year-low) parameter.
    """
    if page < 1:
        raise ValueError("page must be >= 1")

    start = (page - 1) * RESULTS_PER_PAGE
    params = {
        "q": query,
        "start": str(start),
        "hl": "en",
    }
    if year_from is not None:
        params["as_ylo"] = str(year_from)
    request = requests.Request("GET", SCHOLAR_BASE_URL, params=params)
    return request.prepare().url


def looks_rate_limited(html: str) -> bool:
    """Heuristically detect a Google Scholar captcha / rate-limit page."""
    lowered = html.lower()
    markers = (
        "our systems have detected unusual traffic",
        "please show you're not a robot",
        "gs_captcha",
        "/sorry/",
    )
    return any(marker in lowered for marker in markers)


def _create_driver(
    profile_dir: str | None = DEFAULT_PROFILE_DIR,
    headful: bool = False,
):
    """Create a Chrome WebDriver configured to look like a real user."""
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("selenium is not installed")

    options = ChromeOptions()
    if not headful:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument(f"--user-agent={DEFAULT_HEADERS['User-Agent']}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if profile_dir:
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={os.path.abspath(profile_dir)}")

    driver = webdriver.Chrome(options=options)
    # Hide the common headless-Chrome fingerprints on every new document.
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_SCRIPT},
        )
    except WebDriverException as exc:  # pragma: no cover - best effort only
        logger.debug("Could not inject stealth script: %s", exc)
    return driver


def _restart_driver(
    driver,
    profile_dir: str | None = DEFAULT_PROFILE_DIR,
    headful: bool = False,
):
    """Quit a possibly-dead driver and return a fresh one, or ``None`` on failure."""
    if driver is not None:
        try:
            driver.quit()
        except WebDriverException as exc:  # pragma: no cover - best effort
            logger.debug("Error while quitting browser: %s", exc)

    try:
        return _create_driver(profile_dir=profile_dir, headful=headful)
    except WebDriverException as exc:
        print(
            f"[warn] could not restart browser ({exc}); "
            "falling back to requests",
            file=sys.stderr,
        )
        return None


def browser_fetch_html(
    driver,
    url: str,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> str:
    """Fetch a URL with a real browser and return the rendered HTML."""
    driver.get(url)

    try:
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except TimeoutException:
        # Even if the wait times out, fall through and grab whatever we have.
        logger.debug("Timed out waiting for page body at %s", url)

    # Small human-like pause so JS / cookies settle.
    time.sleep(random.uniform(1.0, 2.0))
    return driver.page_source


def _wait_for_captcha_solved(
    driver,
    timeout: float = DEFAULT_CAPTCHA_WAIT_SECONDS,
) -> bool:
    """In headful mode, wait for the user to solve a captcha manually."""
    print(
        "\n[action required] A captcha was detected. Please solve it in the "
        f"browser window. Waiting up to {int(timeout)}s...",
        file=sys.stderr,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2.0)
        try:
            html = driver.page_source
        except WebDriverException:
            return False
        if not looks_rate_limited(html):
            print("[ok] Captcha solved, continuing.", file=sys.stderr)
            return True
    print("[error] Timed out waiting for the captcha to be solved.", file=sys.stderr)
    return False


def fetch_html(
    url: str,
    session: requests.Session,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """Fetch a URL with ``requests`` and return its HTML, retrying on failures.

    This is the fallback path used when a browser is unavailable.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 30))
            continue

        if response.status_code == 429:
            last_error = GoogleScholarRateLimitError(
                f"HTTP 429 (too many requests) for {url}"
            )
            time.sleep(min(2 ** attempt, 30))
            continue

        if response.status_code >= 500:
            last_error = requests.HTTPError(
                f"HTTP {response.status_code} for {url}"
            )
            time.sleep(min(2 ** attempt, 30))
            continue

        response.raise_for_status()

        if looks_rate_limited(response.text):
            raise GoogleScholarRateLimitError(
                "Google Scholar returned a captcha / rate-limit page. "
                "Try again later or increase --delay."
            )

        return response.text

    if last_error is not None:
        raise last_error
    raise requests.RequestException(f"Failed to fetch {url}")


def download_pages(
    query: str,
    pages: int,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    use_browser: bool = True,
    profile_dir: str | None = DEFAULT_PROFILE_DIR,
    headful: bool = False,
    year_from: int | None = DEFAULT_YEAR_FROM,
) -> list[Path]:
    """Download ``pages`` result pages for ``query`` into ``output_dir``.

    If ``year_from`` is set, only results published in that year or later are
    requested (via Google Scholar's ``as_ylo`` parameter).
    """
    if pages < 1:
        raise ValueError("pages must be >= 1")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    # Prefer a real browser; fall back to requests if it is unavailable.
    driver = None
    if use_browser:
        if SELENIUM_AVAILABLE:
            try:
                driver = _create_driver(
                    profile_dir=profile_dir, headful=headful
                )
            except WebDriverException as exc:
                print(
                    f"[warn] could not start browser ({exc}); "
                    "falling back to requests",
                    file=sys.stderr,
                )
                driver = None
        else:
            print(
                "[warn] selenium is not installed; falling back to requests. "
                "Install it with: pip install selenium",
                file=sys.stderr,
            )

    saved: list[Path] = []
    # Tracks the current browser mode; may be escalated to headful on captcha.
    current_headful = headful

    try:
        with tqdm(total=pages, desc="Downloading", unit="page") as bar:
            page = 1
            while page <= pages:
                url = build_search_url(query, page, year_from=year_from)
                filename = f"{page}.html"
                filepath = out_dir / filename

                try:
                    if driver is not None:
                        html = browser_fetch_html(
                            driver, url, wait_seconds=wait_seconds
                        )
                        if looks_rate_limited(html):
                            if not current_headful:
                                # Headless was detected. Restart in headful
                                # mode so the user can solve the captcha, then
                                # retry this same page.
                                print(
                                    "\n[warn] Captcha detected in headless "
                                    "mode; restarting in a visible browser "
                                    "so you can solve it...",
                                    file=sys.stderr,
                                )
                                current_headful = True
                                driver = _restart_driver(
                                    driver,
                                    profile_dir=profile_dir,
                                    headful=True,
                                )
                                if driver is None:
                                    raise GoogleScholarRateLimitError(
                                        "Google Scholar returned a captcha / "
                                        "rate-limit page and the browser "
                                        "could not be restarted in headful "
                                        "mode. Try increasing --delay or "
                                        "waiting a while."
                                    )
                                continue  # retry the same page
                            if _wait_for_captcha_solved(driver):
                                html = driver.page_source
                            else:
                                raise GoogleScholarRateLimitError(
                                    "Google Scholar returned a captcha / "
                                    "rate-limit page that was not solved in "
                                    "time. Try increasing --delay or waiting "
                                    "a while."
                                )
                    else:
                        html = fetch_html(
                            url,
                            session=session,
                            timeout=timeout,
                            max_retries=max_retries,
                        )
                except GoogleScholarRateLimitError as exc:
                    print(f"\n[error] {exc}", file=sys.stderr)
                    break
                except (requests.RequestException, WebDriverException) as exc:
                    print(f"\n[error] page {page}: {exc}", file=sys.stderr)
                    # A dead browser session would make every later page fail
                    # too, so try to bring it back before moving on.
                    if driver is not None and isinstance(exc, WebDriverException):
                        driver = _restart_driver(
                            driver,
                            profile_dir=profile_dir,
                            headful=current_headful,
                        )
                    if bar is not None:
                        bar.update(1)
                    page += 1
                    continue

                filepath.write_text(html, encoding="utf-8")
                saved.append(filepath)

                if bar is not None:
                    bar.update(1)

                if page < pages and delay_seconds > 0:
                    time.sleep(delay_seconds)
                page += 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException as exc:  # pragma: no cover - best effort
                logger.debug("Error while quitting browser: %s", exc)

    return saved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download static HTML pages from Google Scholar.",
    )
    parser.add_argument(
        "--query",
        required=True,
        help='Search query, e.g. "machine learning survey".',
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=25,
        help="Number of result pages to download (default: 25).",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f'Directory to store downloaded HTML (default: "{DEFAULT_OUTPUT_DIR}").',
    )
    parser.add_argument(
        "--profile-dir",
        default=DEFAULT_PROFILE_DIR,
        help=(
            "Persistent Chrome profile directory. Reusing it keeps the "
            "session/cookies across runs, which greatly reduces captchas "
            f'(default: "{DEFAULT_PROFILE_DIR}").'
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds to wait between requests (default: {DEFAULT_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-request timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help=(
            "Seconds to wait for the browser to load each page "
            f"(default: {DEFAULT_WAIT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max retries per page (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=DEFAULT_YEAR_FROM,
        help=(
            "Only include results published in this year or later "
            f"(default: {DEFAULT_YEAR_FROM}). Use 0 to disable the filter."
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Use plain requests instead of a headless browser.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help=(
            "Run a visible browser instead of headless. Use this to solve a "
            "captcha manually; the solved session is saved in --profile-dir."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.pages < 1:
        print("[error] --pages must be >= 1", file=sys.stderr)
        return 2

    # A value of 0 (or negative) disables the year filter.
    year_from = args.year_from if args.year_from and args.year_from > 0 else None

    print(f'Query: "{args.query}"')
    print(f"Pages: 1..{args.pages}")
    print(f"Output: {os.path.abspath(args.output_dir)}")
    print(f"Year from: {year_from if year_from is not None else 'any'}")
    print(f"Mode: {'requests' if args.no_browser else 'browser'}")
    if not args.no_browser:
        print(f"Profile: {os.path.abspath(args.profile_dir)}")
        print(f"Headful: {args.headful}")

    try:
        saved = download_pages(
            query=args.query,
            pages=args.pages,
            output_dir=args.output_dir,
            delay_seconds=args.delay,
            timeout=args.timeout,
            wait_seconds=args.wait,
            max_retries=args.max_retries,
            use_browser=not args.no_browser,
            profile_dir=args.profile_dir,
            headful=args.headful,
            year_from=year_from,
        )
    except KeyboardInterrupt:
        print("\n[interrupted] Stopping.", file=sys.stderr)
        return 130

    print(f"\nSaved {len(saved)} page(s) to {os.path.abspath(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
