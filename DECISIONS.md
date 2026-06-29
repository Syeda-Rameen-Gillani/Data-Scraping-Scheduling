# Case Law Scraper – Design Decisions

## 1. Data Source

Data is extracted from the Sindh High Court case law portal:

```
https://caselaw.shc.gov.pk/caselaw/search-all/search
```

The site renders results via an AJAX call to a dedicated backend endpoint:

```
https://caselaw.shc.gov.pk/caselaw/AJAX_PUBLIC.php
```

The scraper posts directly to this endpoint rather than driving a browser,
which is simpler, faster, and produces less load on the server.

---

## 2. Scraping Approach

The scraper sends POST requests using Python `requests`. The server responds
with JSON, where the actual case data is embedded as an HTML table inside the
`msg` field. BeautifulSoup parses that HTML and extracts structured records.

Pagination is handled by incrementing a page counter in each POST payload.
The loop stops automatically when a page returns no new records, so there is
no hard-coded page limit in production — the scraper always collects
everything the site has.

Code is split into three focused modules:

| File | Responsibility |
|---|---|
| `scraper.py` | HTTP requests, HTML parsing, pagination |
| `storage.py` | Persistence, deduplication, run snapshots |
| `scheduler.py` | Automation, cron schedule, error isolation |

---

## 3. JSON Schema

Each scraped case is stored as a JSON object. All seven fields are always
present; optional fields carry `null` rather than being omitted. This keeps
the schema flat and predictable for any downstream consumer.

```json
{
  "code":        "SHC/HCA/2023/001",
  "s_no":        "1",
  "citation":    "2023 CLD 100",
  "topic":       "Contract",
  "case_no":     "HCA 1/2023",
  "detail_url":  "https://caselaw.shc.gov.pk/caselaw/detail/SHC/HCA/2023/001",
  "_scraped_at": "2025-08-01T02-00-00Z"
}
```

### Field reference

| Field | Type | Nullable | Description |
|---|---|---|---|
| `code` | string | No | Internal case code; primary key for deduplication |
| `s_no` | string | No | Serial number from the results table |
| `citation` | string | Yes | Human-readable citation (e.g. `2023 CLD 100`) |
| `topic` | string | Yes | Legal subject/category assigned by the court |
| `case_no` | string | Yes | Official case reference number (e.g. `HCA 1/2023`) |
| `detail_url` | string | Yes | Absolute URL to the full case detail page |
| `_scraped_at` | string | No | UTC timestamp of the scrape run (ISO 8601) |

`code` is the only field guaranteed non-null because it is used as the
deduplication key; a record with no code is dropped at ingest. `s_no` and
`_scraped_at` are always populated by the scraper itself. The remaining four
fields reflect what the site provides and may be null when the site omits them.

### Why `null` instead of omitting fields

A consistent seven-key object means downstream code can access any field
without a key-existence check. It also makes schema changes easier to spot
in diffs.

---

## 4. Failure Handling

| Layer | Mechanism | Detail |
|---|---|---|
| Network | Timeout | Every request times out after 20 s |
| Network | Retries | Up to 3 attempts per page |
| Network | Back-off | Wait = 5 s × attempt number (5 s, 10 s, 15 s) |
| Network | Partial failure | If a page fails all retries, the run stops early with whatever was collected so far — no crash, no data loss |
| Parsing | Graceful empty | If the HTML has no `tblExport` table, `_parse_table` returns `[]` and the loop terminates cleanly |
| Storage | Atomic writes | Master file is written to a `.tmp` sibling first, then renamed — a crash mid-write cannot corrupt the existing file |
| Storage | Corrupt file | If the master JSON fails to parse on load, the scraper logs the error and starts from an empty store rather than crashing |
| Scheduler | Exception isolation | The job function wraps everything in a broad `try/except` so an unhandled error is logged but does not kill the scheduler process |

---

## 5. Deduplication and Idempotency

The `code` field is the primary key. On each run `storage.upsert()`:

1. Loads the master store into a dict keyed by `code`.
2. For each incoming record:
   - **New code** → insert.
   - **Existing code, data changed** → overwrite.
   - **Existing code, data unchanged** → skip (counter incremented).
3. Saves the updated store atomically.
4. Writes a per-run snapshot to `output/runs/run_<timestamp>.json`.

The `_scraped_at` timestamp is excluded from the change comparison so that
re-scraping identical data never counts as an update. Running the scraper
twice on the same data produces exactly the same master file both times.

---

## 6. Scheduler Choice — APScheduler

APScheduler was chosen over the alternatives for these reasons:

- **Cron vs APScheduler**: raw `cron` works but requires OS-level setup, cannot
  be version-controlled alongside the code, and gives no Python-level error
  handling. APScheduler keeps the schedule in code.
- **APScheduler vs Celery Beat**: Celery Beat is the right choice when you
  already have a Celery worker fleet and need distributed task execution. For a
  single-process scraper that runs once a day, Celery's broker dependency
  (Redis/RabbitMQ) is unnecessary overhead.
- **APScheduler vs simple `schedule` library**: APScheduler has built-in
  `coalesce` and `misfire_grace_time` semantics that handle the case where the
  process was down at the scheduled time. The `schedule` library has no
  equivalent.

The job is configured as:

```python
CronTrigger(hour=2, minute=0)   # 02:00 Asia/Karachi every day
max_instances=1                  # never run two overlapping scrapes
coalesce=True                    # if missed, run once on restart, not N times
misfire_grace_time=3600          # tolerate up to 1 h of downtime/clock drift
```

`Asia/Karachi` was chosen because the SHC portal is a Pakistani court and
judgments are most likely published during business hours PKT, making 02:00
PKT a low-traffic window that is also safe for the target server.

---

## 7. Site Etiquette

- **`robots.txt`**: checked once per process run (result cached) before any
  data request is made. If the URL is disallowed, the scraper returns an
  empty list without making further requests.
- **User-Agent**: identifies the bot as `CaseLawResearchBot/1.0` so the site
  administrator can identify and contact the operator if needed.
- **Throttle**: a 2-second sleep between pages keeps request rates well within
  what a human researcher would generate.
- **No parallelism**: requests are strictly sequential — no threading or async
  concurrency that could accidentally flood the server.

---

## 8. Testing Strategy

Tests live in `test_scraper.py` and cover every function in `scraper.py`.
No network requests are made during tests — all HTTP calls, `robots.txt`
reads, and `time.sleep` calls are mocked.

| Test class | What it covers |
|---|---|
| `TestParseTable` | HTML parsing: empty input, missing table, header skipped, short rows skipped, all six fields extracted, whitespace stripped, empty strings → `null`, relative URLs made absolute |
| `TestBasePayload` | Default keys present, overrides applied, extra keys added, defaults not mutated between calls |
| `TestRobotsAllow` | Allow/disallow returned correctly, `robots.txt` fetched only once (caching), graceful proceed when `robots.txt` is unreachable |
| `TestPostWithRetry` | Success on first attempt, `None` after all retries exhausted, exact retry count, sleep between retries but not after the last, success on second attempt, HTTP error → `None`, JSON error → `None`, back-off increases each attempt |
| `TestScrapeCases` | `robots.txt` blocks → empty list, single page, empty first page, `None` from network, multi-page collection, dedup across pages, loop stops when all records are duplicates, `max_pages` cap, page number increments in payload, throttle sleep called, `caseno`/`caseyear` forwarded |

Run the full suite with:

```bash
pytest test_scraper.py -v
```

---

## 9. Output Layout

```
output/
  cases_master.json        # full deduplicated dataset, updated on every run
  runs/
    run_2025-08-01T02-00-00Z.json   # snapshot of what each run collected
logs/
  scraper.log              # per-request detail
  scheduler.log            # job start/stop and summary
```

The per-run snapshots make it easy to audit exactly what changed between runs
without diffing the master file.