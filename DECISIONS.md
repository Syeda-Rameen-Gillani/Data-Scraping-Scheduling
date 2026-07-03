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

---

## 10. Incremental Ingestion into Weaviate

`ingestion_pipeline.py` decides what needs to be (re-)embedded using a local
manifest file (`output/ingestion_manifest.json`), **not** a query against
Weaviate itself.

### Why not just ask Weaviate what it already has?

An earlier version pulled every existing `chunk_id` out of Weaviate via
`collection.iterator()` before each run, to know what to skip. That works at
small scale, but the cost of that scan grows with the *total* size of the
collection, not with the amount of new data — so ingestion gets slower every
single day even on days where nothing changed. That's the opposite of what
"incremental" should mean.

### The manifest approach

The manifest is a flat `{case_code: content_hash}` mapping, kept on the same
server as the scheduler and ingestion job (per the co-location requirement).
On each run:

1. Hash the current markdown text for each case.
2. If `manifest[case_code]` already equals that hash → **skip completely**.
   No re-chunking, no re-embedding, no Weaviate call at all for that case.
3. If the case is new, or the hash changed → delete that case's existing
   chunks from Weaviate (`Filter.by_property("case_code")`, a targeted
   delete, not a scan) and re-chunk/re-embed only that case.
4. Update the manifest with the new hash.

Cost of step 2 is a single dict lookup, independent of how many chunks exist
in Weaviate — so the job scales with *how much changed today*, not with the
size of the entire historical dataset.

This also fixes a correctness gap in the scan-based approach: it never
deleted stale chunks when a case's content changed, so an edited judgment
would accumulate duplicate/outdated chunks over time instead of being
cleanly replaced.

`chunk_id` (a hash of case + position + text) is still computed and stored
per chunk. It's no longer used for the skip/ingest decision, but it remains
useful as a stable, content-addressed primary key for that chunk if you ever
need to look one up directly.

---

## 11. Chunking Strategy: Structured Metadata vs. PDF Judgment Text

This pipeline handles two genuinely different kinds of content, and they are
deliberately **not** chunked the same way.

### Scraped structured metadata — not chunked at all

Fields scraped directly off the case-law portal (`case_no`, `citation`,
`topic`, `code`, `detail_url`) are short, atomic key/value data. They are
attached as Weaviate **properties** on every chunk belonging to that case,
not run through the chunker. Splitting a value like `"HCA 1/2023"` into
overlapping character windows would gain nothing and would actively destroy
the one piece of information it holds. Structured data doesn't need
windowing; it needs to be filterable and returned intact, which is exactly
what Weaviate properties (and the `Filter.by_property` exact-match lookup in
`/chat` for case-number queries) give us.

### PDF judgment text — paragraph-aware windowing

The actual judgment content comes from `fitz`/PyMuPDF's raw text extraction
of the source PDF (`pdf_to_markdown()` in `scraper.py`). That extraction has
**no headers, no sections, no markdown structure** — it's continuous prose
with paragraph breaks marked only by blank/whitespace lines and Windows
`\r\n` endings. Because there's no structural metadata to chunk *around*
(no "FACTS" / "JUDGMENT" section headers to split on), the only viable
strategy is windowing — but the window should respect the one structural
signal that does exist: paragraph breaks.

`chunk_text()` in `chunker.py`:
1. Normalizes line endings and collapses whitespace-only lines.
2. Splits on blank-line boundaries into paragraphs, joining wrapped lines
   within a paragraph into a single readable line (PDF line wraps are
   visual, not semantic).
3. Packs whole paragraphs together up to `chunk_size` (700 chars), so a
   chunk boundary lands between paragraphs/sentences rather than mid-word.
4. Falls back to a plain sliding window only for the rare paragraph that
   exceeds `chunk_size` on its own, since at that point there's no smaller
   natural boundary left to respect.
5. Carries a small overlap (100 chars) from the end of one chunk into the
   next, so a citation shown to the user doesn't lose context right at the
   seam.

### Why this differs from "chunking a PDF" in the generic sense

A generic PDF chunker often chunks *by page* or preserves layout artifacts
(headers/footers repeated per page, footnotes, page numbers) because the
PDF's structure carries meaning (e.g., a manual with numbered sections).
Here, page boundaries are an artifact of printing, not of the argument's
structure — a judgment's reasoning routinely spans a page break mid-sentence.
Chunking by page would reintroduce exactly the kind of arbitrary, meaning-
blind cut that paragraph-aware windowing is meant to avoid. So instead of
chunking by page, this pipeline extracts the PDF's text once (flattening
away the page structure) and then chunks that flattened text by paragraph —
treating the PDF as a source of prose to reflow, not as a source of
page-shaped units to preserve.page-shaped units to preserve.

---

## 12. PDF Sourcing and Storage: Local Cache + Google Drive as the Public URL

Each judgment PDF is downloaded once (`pdf_pipeline.py`), then uploaded to a
shared Google Drive folder (`drive_utils.py`) with `anyone/reader` permission,
and the resulting `https://drive.google.com/file/d/<id>/view` link — not the
original SHC portal URL — is what gets stored as `pdf_url` in the per-case
JSON metadata and, from there, as a Weaviate property on every chunk.

Two reasons for re-hosting rather than pointing directly at the source site:

1. **Stability.** The SHC portal's PDF links are not guaranteed to stay valid
   indefinitely (session-scoped paths, site restructuring), whereas a Drive
   file with a fixed ID is a stable citation target for as long as the file
   exists.
2. **The task explicitly asks for a public, view-only URL in the metadata**,
   which Drive's sharing permissions provide directly — the case JSON never
   needs to touch the SHC site again once the PDF is uploaded.

Before uploading, `upload_pdf_to_drive()` checks whether a file with the same
name already exists in the target folder and returns its existing URL instead
of re-uploading — this keeps re-runs (e.g. after a scrape re-detects a case
that was already processed) from creating duplicate files in Drive.

---

## 13. Chat Endpoint: Retrieval + Grounding Strategy

`/chat` in `app.py` implements a small but deliberate two-path retrieval
strategy rather than always going straight to vector search:

1. **Exact case-number match.** If the query contains something matching
   `\d+/\d{4}` (e.g. "68/2013"), it's treated as a literal case-number lookup
   and answered via `Filter.by_property("case_no")` — an exact metadata
   filter — instead of semantic search. A case number is an identifier, not
   a concept; embedding it and hoping the nearest vectors happen to contain
   the same digits is strictly worse than an exact filter when the user has
   clearly given you the exact key.
2. **Semantic search** for everything else: the query is embedded with the
   same `all-MiniLM-L6-v2` model used at ingestion time and matched via
   `near_vector` against the top `TOP_K=5` chunks.

Grounding is enforced at the prompt level, not just by "please cite your
sources": the LLM is explicitly instructed to answer only from the retrieved
excerpts, told to reply with a fixed refusal string
(`"I don't have enough information to answer that."`) when the sources don't
contain the answer, and told not to invent facts. Retrieved chunks are
deduplicated by `case_code` before being turned into a `citations` list, so a
case that contributed five chunks to the answer shows up once in the
citation list, not five times — each citation carries `case_code`, `case_no`,
`citation`, and the Drive `pdf_url`, so the user can go straight to the
source PDF.



## 14. Secrets and Configuration

- Google OAuth credentials (`credentials.json`) and the resulting cached
  token (`token.json`) are kept out of version control. They must be
  provisioned per-environment rather than shipped with the repo.
- Weaviate runs locally with anonymous access enabled
  (`AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true` in `docker-compose.yml`).
  This is acceptable for a single-developer local setup but would need an
  API key and network restriction before running on any shared or
  internet-reachable host.
- Model names (embedding model, LLM model), the Weaviate collection name, and
  the Drive folder ID are currently constants defined at the top of their
  respective files rather than environment variables. This keeps the code
  simple for a single-environment project but should move to `.env`/config
  before there's more than one deployment target (e.g. staging vs prod Drive
  folders, or swapping the LLM model without editing source).

---
