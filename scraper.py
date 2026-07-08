import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse
import os
import json
import fitz
session = requests.Session()

import s3_utils
from metadata_enrichment import build_full_metadata
from external_api import upsert_judgment, ApiAuthError

COURT_NAME = "Sindh High Court"

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


def get_leaf(pdf_url: str) -> str:
    """
    Section 3: <leaf> is the leaf filename of the source PDF URL, without
    extension. E.g. ".../2026SHC153.pdf" -> "2026SHC153".
    """
    path = urlparse(pdf_url).path
    filename = os.path.basename(path)
    return os.path.splitext(filename)[0]


def build_filenames(leaf: str) -> dict:
    """
    Returns the three filenames (with court prefix) for a given <leaf>,
    per Section 3's naming convention.
    """
    stem = f"{COURT_NAME} - {leaf}"
    return {
        "pdf": f"{stem}.pdf",
        "md": f"{stem}.md",
        "json": f"{stem}.json",
        "stem": stem,
    }

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
    
def download_pdf(pdf_url, pdf_filename):
    if not pdf_url:
        return None

    try:
        if "/caselaw/" not in pdf_url:
            pdf_url = pdf_url.replace(
                "https://caselaw.shc.gov.pk/",
                "https://caselaw.shc.gov.pk/caselaw/"
            )

        r = session.get(pdf_url, headers=HEADERS, timeout=60)
        if "application/pdf" not in r.headers.get("Content-Type", ""):
            print("Skipping non-PDF:", pdf_url)
            return None

        path = os.path.join("pdfs", pdf_filename)

        with open(path, "wb") as f:
            f.write(r.content)

        print("Downloaded:", path)
        return path

    except Exception as e:
        print("Failed:", pdf_url, e)
        return None



def pdf_to_markdown(pdf_path, md_filename):
    doc = fitz.open(pdf_path)

    markdown = ""

    for page in doc:
        markdown += page.get_text()
        markdown += "\n\n"

    output_path = os.path.join("markdown", md_filename)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print("Markdown saved:", output_path)

    return output_path, markdown

def write_json(json_path: str, metadata: dict) -> None:
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def process_new_case(case: dict, leaf: str, filenames: dict) -> dict | None:
    """
    Full pipeline for a judgment we have never seen before:
    download -> extract -> enrich -> upload to S3 -> POST to API.

    Returns the state entry to store for this judgment, or None on failure.
    """
    pdf_url = case.get("pdf_url")
    if not pdf_url:
        log.warning("No pdf_url for case %s — skipping.", case.get("code"))
        return None

    pdf_path = download_pdf(pdf_url, filenames["pdf"])
    if not pdf_path:
        log.error("PDF download failed for %s — skipping.", filenames["pdf"])
        return None

    md_path, markdown_text = pdf_to_markdown(pdf_path, filenames["md"])

    metadata = build_full_metadata(
        case=case,
        pdf_filename=filenames["pdf"],
        markdown_text=markdown_text,
        reference_url=pdf_url,
    )

    json_path = os.path.join("json", filenames["json"])
    os.makedirs("json", exist_ok=True)
    write_json(json_path, metadata)

    # Section 9 — upload PDF, MD, JSON to S3 (idempotent; skip if already there).
    s3_utils.upload_file(pdf_path, "pdfs")
    s3_utils.upload_file(md_path, "markdown")
    s3_utils.upload_file(json_path, "metadata")

    # Section 10.5 — only call the API AFTER S3 upload succeeds.
    try:
        result = upsert_judgment(metadata, known_to_api=False)
    except ApiAuthError as exc:
        log.error("API auth failed (%s) — halting run.", exc)
        raise

    if not result.success:
        log.error(
            "API upsert failed for %s (status=%s, action=%s) — "
            "not marking as processed; will retry next run.",
            filenames["stem"], result.status_code, result.action,
        )
        return None

    log.info("Processed new judgment: %s (%s)", filenames["stem"], result.action)

    return {
        "fileName": filenames["stem"],
        "citation": case.get("citation"),
    }


def process_citation_update(case: dict, leaf: str, filenames: dict, state_entry: dict) -> dict | None:
    """
    Section 11.2 — citation appeared/changed for an already-processed judgment.
    Does NOT re-download the PDF or re-extract the markdown; only rebuilds
    and re-uploads the JSON, then PUTs the update to the API.
    """
    md_path = os.path.join("markdown", filenames["md"])
    if not os.path.exists(md_path):
        log.warning(
            "Citation changed for %s but local markdown is missing — "
            "cannot rebuild metadata without re-processing. Skipping.",
            filenames["stem"],
        )
        return state_entry

    with open(md_path, encoding="utf-8") as f:
        markdown_text = f.read()

    metadata = build_full_metadata(
        case=case,
        pdf_filename=filenames["pdf"],
        markdown_text=markdown_text,
        reference_url=case.get("pdf_url"),
    )

    json_path = os.path.join("json", filenames["json"])
    os.makedirs("json", exist_ok=True)
    write_json(json_path, metadata)

    # Section 11.2 step 3 — this is the one case where we MUST overwrite
    # an existing S3 key, bypassing the normal idempotency skip.
    s3_utils.upload_file(json_path, "metadata", overwrite=True)

    try:
        result = upsert_judgment(metadata, known_to_api=True)
    except ApiAuthError as exc:
        log.error("API auth failed (%s) — halting run.", exc)
        raise

    if not result.success:
        log.error(
            "Citation-update API call failed for %s (status=%s) — "
            "keeping old citation in state; will retry next run.",
            filenames["stem"], result.status_code,
        )
        return state_entry

    log.info("Citation updated for %s -> %s", filenames["stem"], case.get("citation"))

    return {
        "fileName": filenames["stem"],
        "citation": case.get("citation"),
    }


def process_case(case: dict, state: dict) -> None:
    """
    Section 11.1 — decide which path a case takes on this run: new judgment,
    citation update, or no-op (already processed, citation unchanged).
    Mutates `state` in place.
    """
    pdf_url = case.get("pdf_url")
    identifier = case.get("code")

    if not identifier:
        log.warning("Case missing 'code' (identifier) — skipping: %s", case)
        return
    if not pdf_url:
        log.info("No PDF attached for case %s (%s) — skipping.", identifier, case.get("case_no"))
        return

    leaf = get_leaf(pdf_url)
    filenames = build_filenames(leaf)

    existing = state.get(identifier)

    if existing is None:
        entry = process_new_case(case, leaf, filenames)
        if entry:
            state[identifier] = entry
        return

    current_citation = (case.get("citation") or "").strip() or None
    stored_citation = existing.get("citation")

    if current_citation == stored_citation:
        log.info("No change for %s — skipping.", filenames["stem"])
        return

    # Section 11.4 — citation regression: had one, now listing shows none.
    # Log and leave existing data alone rather than blanking a valid citation.
    if stored_citation and not current_citation:
        log.warning(
            "Citation regression detected for %s (was %s, listing now empty) — "
            "leaving existing data untouched.",
            filenames["stem"], stored_citation,
        )
        return

    entry = process_citation_update(case, leaf, filenames, existing)
    if entry:
        state[identifier] = entry


def run():
    """
    Full re-runnable sync: download state -> scrape -> process each case,
    persisting state after every judgment (not just at the end) so a
    long run can be safely interrupted (Ctrl+C) or crash partway through
    without losing already-completed work.
    """
    state = s3_utils.download_state_file()
    log.info("Loaded state: %d judgment(s) previously processed.", len(state))

    cases = scrape_cases(max_pages=1)
    log.info("Total cases fetched: %d", len(cases))

    processed_count = 0

    try:
        for case in cases:
            before = dict(state)
            process_case(case, state)

            if state != before:
                s3_utils.upload_state_file(state)
                processed_count += 1
                log.info(
                    "State saved after judgment %d/%d.",
                    processed_count, len(cases),
                )
    except KeyboardInterrupt:
        log.warning(
            "Interrupted by user — state is up to date as of the last "
            "completed judgment. Safe to re-run; already-processed "
            "judgments will be skipped."
        )
        raise
    finally:
        # Belt-and-suspenders: also save on any other exception, in case
        # `state` was mutated after the last per-judgment save but before
        # the exception was raised.
        s3_utils.upload_state_file(state)
        log.info("Final state uploaded: %d judgment(s) now tracked.", len(state))


if __name__ == "__main__":
    run()