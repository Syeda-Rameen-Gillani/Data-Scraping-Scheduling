import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin
import os
import fitz
session = requests.Session()
from drive_utils import upload_pdf_to_drive

os.makedirs("logs", exist_ok=True)
os.makedirs("pdfs", exist_ok=True)
os.makedirs("markdown", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("logs/scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

BASE_URL   = "https://caselaw.shc.gov.pk"
AJAX_URL   = f"{BASE_URL}/caselaw/AJAX_PUBLIC.php"
ROBOTS_URL = f"{BASE_URL}/robots.txt"

HEADERS = {
    "User-Agent":        "CaseLawResearchBot/1.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer":          f"{BASE_URL}/caselaw/search-all/search",
}

REQUEST_TIMEOUT = 60
RETRY_LIMIT     = 3
RETRY_BACKOFF   = 5   # seconds; multiplied by attempt number (1×, 2×, 3×)
THROTTLE        = 5   # seconds between successful page fetches

# Cache the RobotFileParser so we only hit robots.txt once per process run.
_robot_parser: RobotFileParser | None = None


def _get_robot_parser() -> RobotFileParser:
    """Return a cached RobotFileParser, fetching robots.txt only on first call."""
    global _robot_parser
    if _robot_parser is None:
        rp = RobotFileParser()
        rp.set_url(ROBOTS_URL)
        try:
            rp.read()
            log.info("robots.txt loaded successfully.")
        except Exception as exc:
            log.warning("Could not read robots.txt (%s) — proceeding cautiously.", exc)
        _robot_parser = rp
    return _robot_parser


def _robots_allow(url: str) -> bool:
    """Return True if robots.txt permits fetching *url* with our User-Agent."""
    rp = _get_robot_parser()
    allowed = rp.can_fetch(HEADERS["User-Agent"], url)
    if not allowed:
        log.error("robots.txt disallows fetching %s — aborting.", url)
    return allowed


def _post_with_retry(payload: dict) -> dict | None:
    """
    POST *payload* to AJAX_URL with retries and exponential-ish back-off.
    Returns the parsed JSON dict, or None if all attempts fail.
    """
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = session.post(
                AJAX_URL,
                data=payload,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            log.warning("Attempt %d/%d timed out.", attempt, RETRY_LIMIT)
        except requests.exceptions.HTTPError as exc:
            log.warning("Attempt %d/%d HTTP error: %s", attempt, RETRY_LIMIT, exc)
        except requests.exceptions.RequestException as exc:
            log.warning("Attempt %d/%d network error: %s", attempt, RETRY_LIMIT, exc)
        except ValueError as exc:
            log.warning("Attempt %d/%d JSON decode error: %s", attempt, RETRY_LIMIT, exc)

        if attempt < RETRY_LIMIT:
            wait = RETRY_BACKOFF * attempt
            log.info("Waiting %ds before retry ...", wait)
            time.sleep(wait)

    log.error("All %d attempts failed for payload: %s", RETRY_LIMIT, payload)
    return None


def _parse_table(html: str) -> list[dict]:
    if "tblExport" not in html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "tblExport"})
    if not table:
        return []

    records = []

    for row in table.find_all("tr")[1:]:  # skip header row
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        link_tag = cols[0].find("a") or cols[2].find("a")
        detail_url = (
            urljoin(BASE_URL, link_tag["href"])
            if link_tag and link_tag.get("href")
            else None
        )

        pdf_tag = None

        for a in row.find_all("a", href=True):
            href = a["href"]
            if "view-file" in href or "download-file" in href or "hc-link.php" in href:
                pdf_tag = a
                break

        pdf_url = urljoin(BASE_URL, pdf_tag["href"]) if pdf_tag else None
        
        
        records.append({
            "code": cols[0].text.strip() or None,
            "s_no": cols[1].text.strip() or None,
            "citation": cols[2].text.strip() or None,
            "topic": cols[3].text.strip() or None,
            "case_no": cols[4].text.strip() or None,
            "detail_url": detail_url,
            "pdf_url": pdf_url,
        })

    return records



def _base_payload(**overrides) -> dict:
    """
    Return the default POST payload for the judgment-search endpoint.
    Any keyword argument is merged in, overriding the default value.
    """
    payload = {
    "STD_JUDGES": "-1",
    "ALL_JUDGES_M_SELECT": "",
    "ALL_ADVOCATES_M_SELECT": "",
    "ALL_TOPICS_M_SELECT": "",
    "STD_COURTS": "1",
    "CASENO": "",
    "CASEYEAR": "",
    "STD_CASETYPES": "8",
    "STD_BENCHTYPES": "-1",
    "STD_DOCUMENTTYPES": "-1",
    "AFR_TF": "false",
    "PARTYSIDE1_NAMES": "",
    "DATE_ORDER_JUDGMENT": "",
    "DATE_ORDER_JUDGMENT2": "30-Jun-26",
    "CASEGROUP": "5",
    "opt": "search_judgement",
    }
    
    payload.update(overrides)
    return payload


def scrape_cases(
    caseno: str = "",
    caseyear: str = "",
    page_param: str = "page",        # query-string / payload key the site uses for page number
    start_page: int = 1,
    max_pages: int | None = None,    # None  →  keep going until the site returns no more rows
    page_size: int | None = None,    # set if the site exposes a per-page count param
) -> list[dict]:
    """
    Scrape judgment records from the SHC caselaw portal.

    Parameters
    ----------
    caseno      : Filter by case number (empty = no filter).
    caseyear    : Filter by case year  (empty = no filter).
    page_param  : Name of the payload key used to request a specific page.
                  Inspect the real XHR if the site uses a different name.
    start_page  : First page index (usually 1, occasionally 0).
    max_pages   : Hard cap on pages fetched.  Pass None (default) to scrape
                  *all* pages — the loop stops automatically when a page
                  returns zero new records.
    page_size   : If the endpoint accepts a page-size parameter, pass it here.

    Returns
    -------
    List of record dicts (see _parse_table schema above), de-duplicated by
    the 'code' field across all pages.
    """
    _robots_allow(AJAX_URL)
    
    # warm-up request to establish session cookies
    session.get(
    "https://caselaw.shc.gov.pk/caselaw/search-all/search",
    headers=HEADERS,
    timeout=REQUEST_TIMEOUT
    )
    all_records: list[dict] = []
    seen_codes:  set[str]   = set()
    page = start_page

    while True:
        # ── build payload for this specific page ──────────────────────────────
        extra: dict = {
            "CASENO":    caseno,
            "CASEYEAR":  caseyear,
            page_param:  str(page),          # <── was missing in original code
        }
        if page_size is not None:
            extra["page_size"] = str(page_size)

        payload = _base_payload(**extra)
        log.info("Fetching page %d …", page)
        
        print("DEBUG PAYLOAD:", payload)

        data = _post_with_retry(payload)
        if data is None:
            log.warning("Page %d failed — stopping early.", page)
            break

        records = _parse_table(data.get("msg", ""))
        if not records:
            log.info("Page %d returned no records — all pages exhausted.", page)
            break

        new_this_page = 0
        for rec in records:
            key = rec["code"]
            if key and key in seen_codes:
                continue                     # skip true duplicates across pages
            if key:
                seen_codes.add(key)
            all_records.append(rec)
            new_this_page += 1

        log.info(
            "Page %d: %d new record(s) — running total %d.",
            page, new_this_page, len(all_records),
        )

        # Stop if the site returned a page of rows we'd already seen (e.g. the
        # last page repeated).  This prevents an infinite loop on sites that
        # return the final page repeatedly instead of an empty response.
        if new_this_page == 0:
            log.info("No new records on page %d — treating as end of data.", page)
            break

        page += 1

        # Honour the hard cap when one is given.
        if max_pages is not None and (page - start_page) >= max_pages:
            log.info("Reached max_pages=%d — stopping.", max_pages)
            break

        time.sleep(THROTTLE)

    log.info("Scrape complete.  %d unique records collected.", len(all_records))
    return all_records

def open_view_page(url):
    """
    Opens the green-eye page and saves its HTML so we can inspect it.
    """
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    with open("pdfs/test.pdf", "wb") as f:
        f.write(response.content)

    print("PDF saved!")
    
def download_pdf(pdf_url, code):
    if not pdf_url:
        return

    try:
        if "/caselaw/" not in pdf_url:
            pdf_url = pdf_url.replace(
                "https://caselaw.shc.gov.pk/",
                "https://caselaw.shc.gov.pk/caselaw/"
            )

        r = session.get(pdf_url, headers=HEADERS, timeout=60)
        if "application/pdf" not in r.headers.get("Content-Type", ""):
            print("Skipping non-PDF:", pdf_url)
            return

        path = os.path.join("pdfs", f"{code}.pdf")

        with open(path, "wb") as f:
            f.write(r.content)

        print("Downloaded:", path)
        return path

    except Exception as e:
        print("Failed:", pdf_url, e)



def pdf_to_markdown(pdf_path, code):
    doc = fitz.open(pdf_path)

    markdown = ""

    for page in doc:
        markdown += page.get_text()
        markdown += "\n\n"

    output_path = os.path.join("markdown", f"{code}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print("Markdown saved:", output_path)

    return output_path

import json

def save_metadata(case, pdf_path, md_path, drive_url):
    code = case.get("code") or "unknown"

    data = {
        "code": code,
        "citation": case.get("citation"),
        "topic": case.get("topic"),
        "case_no": case.get("case_no"),
        "detail_url": case.get("detail_url"),
        "pdf_url": drive_url,
        "local_pdf": pdf_path,
        "local_markdown": md_path,
    }

    os.makedirs("json", exist_ok=True)

    json_path = os.path.join("json", f"{code}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print("JSON saved:", json_path)

    return json_path

def process_case(case: dict):
    """
    Given a single scraped case record, download its PDF, upload it to
    Drive, convert it to markdown, and save the combined metadata JSON.
    Returns the json_path on success, or None if there was no PDF to process.
    """
    pdf_url = case.get("pdf_url")
    code = case.get("code") or "unknown"

    if not pdf_url:
        return None

    pdf_path = download_pdf(pdf_url, code)
    if not pdf_path:
        return None

    drive_url = upload_pdf_to_drive(pdf_path)
    md_path = pdf_to_markdown(pdf_path, code)
    json_path = save_metadata(case, pdf_path, md_path, drive_url)

    return json_path


if __name__ == "__main__":

    cases = scrape_cases(max_pages=1)

    print(f"Total cases fetched: {len(cases)}")

    for case in cases:
        process_case(case)
