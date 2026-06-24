import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin
import os

os.makedirs("logs", exist_ok=True)

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

REQUEST_TIMEOUT = 20
RETRY_LIMIT     = 3
RETRY_BACKOFF   = 5
THROTTLE        = 2


def _robots_allow(url):
    rp = RobotFileParser()
    rp.set_url(ROBOTS_URL)
    try:
        rp.read()
    except Exception as exc:
        log.warning("Could not read robots.txt (%s) — proceeding cautiously.", exc)
        return True
    allowed = rp.can_fetch(HEADERS["User-Agent"], url)
    if not allowed:
        log.error("robots.txt disallows fetching %s — aborting.", url)
    return allowed


def _post_with_retry(payload):
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = requests.post(
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

    log.error("All %d attempts failed.", RETRY_LIMIT)
    return None


def _parse_table(html):
    if "tblExport" not in html:
        return []
    soup  = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "tblExport"})
    if not table:
        return []
    records = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
        link_tag   = cols[0].find("a") or cols[2].find("a")
        detail_url = urljoin(BASE_URL, link_tag["href"]) if link_tag and link_tag.get("href") else None
        records.append({
            "code":       cols[0].text.strip(),
            "s_no":       cols[1].text.strip(),
            "citation":   cols[2].text.strip() or None,
            "topic":      cols[3].text.strip() or None,
            "case_no":    cols[4].text.strip() or None,
            "detail_url": detail_url,
        })
    return records


def _base_payload(**overrides):
    payload = {
        "STD_JUDGES":              "-1",
        "ALL_JUDGES_M_SELECT":     "",
        "ALL_ADVOCATES_M_SELECT":  "",
        "ALL_TOPICS_M_SELECT":     "",
        "STD_COURTS":              "-1",
        "CASENO":                  "",
        "CASEYEAR":                "",
        "STD_CASETYPES":           "-1",
        "STD_BENCHTYPES":          "-1",
        "STD_DOCUMENTTYPES":       "-1",
        "AFR_TF":                  "false",
        "PARTYSIDE1_NAMES":        "",
        "DATE_ORDER_JUDGMENT":     "",
        "DATE_ORDER_JUDGMENT2":    "",
        "CASEGROUP":               "5",
        "opt":                     "search_judgement",
    }
    payload.update(overrides)
    return payload


def scrape_cases(caseno="", caseyear="", max_pages=5):
    if not _robots_allow(AJAX_URL):
        return []
    all_records = []
    seen_codes  = set()
    for page in range(1, max_pages + 1):
        payload = _base_payload(CASENO=caseno, CASEYEAR=caseyear)
        log.info("Fetching page %d ...", page)
        data = _post_with_retry(payload)
        if data is None:
            log.warning("Page %d failed — stopping.", page)
            break
        records = _parse_table(data.get("msg", ""))
        if not records:
            log.info("No records on page %d — done.", page)
            break
        for rec in records:
            if rec["code"] and rec["code"] in seen_codes:
                continue
            seen_codes.add(rec["code"])
            all_records.append(rec)
        log.info("Page %d: total so far %d records.", page, len(all_records))
        if page < max_pages:
            time.sleep(THROTTLE)
    return all_records