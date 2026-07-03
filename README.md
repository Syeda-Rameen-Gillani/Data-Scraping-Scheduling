# Case Law Scraper & RAG Service — Sindh High Court

Scrapes case records from the [SHC Case Law portal](https://caselaw.shc.gov.pk/caselaw/search-all/search),
downloads and archives the underlying judgment PDFs, converts them to markdown,
ingests them into a Weaviate vector store, and exposes a FastAPI chat endpoint
that answers questions with citations back to the source case.

---

## Project Structure

```
.
├── scraper.py              # HTTP requests, HTML parsing, pagination, PDF/MD/JSON pipeline
├── storage.py               # Upsert logic, master file, run snapshots
├── scheduler.py              # APScheduler entry point: scrape -> process -> ingest, daily
├── pdf_pipeline.py           # Downloads judgment PDFs
├── drive_utils.py            # Uploads PDFs to Google Drive, returns public view-only URL
├── chunker.py                 # Paragraph-aware chunking for judgment text
├── ingestion_pipeline.py       # Incremental embed + upsert into Weaviate
├── weaviate_client.py           # Weaviate connection helper
├── create_collection.py          # One-time Weaviate schema setup
├── app.py                         # FastAPI service: /health, /chat (RAG endpoint)
├── docker-compose.yml               # Local Weaviate instance
├── test_scraper.py                   # Automated tests (no network required)
├── DECISIONS.md                       # Full design rationale
├── logs/                                # Auto-created
├── output/                               # Auto-created: master JSON, run snapshots, ingestion manifest
├── json/, markdown/, pdfs/                 # Per-case artifacts (raw, converted, source)
```

---

## Requirements

Python 3.10+ (uses `X | Y` union syntax). A local [Ollama](https://ollama.com)
install with a pulled model (`llama3.2:3b` by default) and Docker (for Weaviate)
are also required.

```bash
pip install -r requirements.txt
```

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```



## Running the pipeline

### Manual one-off scrape + process + ingest

```bash
python -c "
from scraper import scrape_cases, process_case
from storage import upsert
summary = upsert(scrape_cases())
for case in summary['changed_records']:
    process_case(case)   # downloads PDF, uploads to Drive, converts to markdown, writes JSON
print(summary)
"
python ingestion_pipeline.py   # embeds new/changed cases into Weaviate
```

### Automated daily run

```bash
python scheduler.py
```

Fires daily at **02:00 Asia/Karachi**. Each run: scrapes all pages → upserts
into `output/cases_master.json` → for every new/changed case, downloads the
PDF, uploads it to Google Drive, converts it to markdown, and writes
`json/<code>.json` → then calls the Weaviate ingestion job (`ingest()`), which
only embeds cases whose content hash changed since the last run. Ingestion is
intentionally run in-process, on the same machine, right after the scrape —
not as a separate scheduled job — so the two never drift out of sync and there's
no second server to keep running.

### Serving the API

```bash
uvicorn app:app --reload
```

- `GET /health` — liveness check.
- `GET /chat?q=...` — ask a question about the ingested case law. Embeds the
  query (or detects a literal case number like `68/2013` and does an exact
  metadata filter instead of semantic search), retrieves the top-5 matching
  chunks from Weaviate, and asks a local LLM (Ollama) to answer using only
  those chunks. Returns the answer plus a `citations` list
  (`case_code`, `case_no`, `citation`, `pdf_url`) pointing back to the source
  judgment's Google Drive PDF.

  ```bash
  curl "http://localhost:8000/chat?q=What happened in Adm. Suit 1088/2005?"
  ```

---

## Running the Tests

```bash
pytest test_scraper.py -v
```

All 40 tests run offline. See `DECISIONS.md` §8 for coverage details.
(Ingestion and chat endpoint currently only have manual/ad-hoc verification —
`debug_retrieval.py` is a standalone diagnostic that bypasses the LLM to
inspect raw retrieval results; there's no automated test coverage yet for
`chunker.py` or `ingestion_pipeline.py`.)

---

## Output layout

```
output/
  cases_master.json            # full deduplicated scraped dataset
  runs/run_<timestamp>.json    # per-run snapshot
  ingestion_manifest.json      # {case_code: content_hash} — drives incremental ingestion
json/<code>.json               # per-case metadata: citation, case_no, pdf_url (Drive), local paths
markdown/<code>.md             # PDF text extracted via PyMuPDF
pdfs/<code>.pdf                # locally cached source PDF
logs/scraper.log, scheduler.log
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in your real values:

​```bash
cp .env.example .env
​```

| Variable | Purpose | Required? |
|---|---|---|
| `DRIVE_FOLDER_ID` | Google Drive folder that judgment PDFs get uploaded to | Yes — no default |
| `EMBEDDING_MODEL` | Sentence-transformers model used for both ingestion and query embedding | No — defaults to `all-MiniLM-L6-v2` |
| `LLM_MODEL` | Ollama model used to generate chat answers | No — defaults to `llama3.2:3b` |
| `WEAVIATE_COLLECTION` | Weaviate collection name | No — defaults to `CaseChunk` |
| `TOP_K` | Number of chunks retrieved per chat query | No — defaults to `5` |

> `EMBEDDING_MODEL` must be the same value everywhere — it's used to embed
> chunks at ingestion time and to embed the query at chat time. If they ever
> diverge, semantic search silently breaks (vectors from different models
> aren't comparable).

## Secrets & Configuration

- `credentials.json` (Google OAuth client secret), `token.json` (cached
  user token), and `.env` (your real config values) are all git-ignored and
  must never be committed.
- Weaviate currently runs with anonymous access enabled for local dev
  (`docker-compose.yml`) — fine for a laptop, not for a shared/production host.

  ## One-time setup

Before anything else, set up your `.env` file (see [Environment variables](#environment-variables) below) — the steps here depend on it.

1. **Weaviate** (local, no auth — dev only):
```bash
   docker compose up -d
   python create_collection.py    # creates the Weaviate collection named in WEAVIATE_COLLECTION
```
2. **Google Drive OAuth**: place your OAuth client secret at `credentials.json`
   (never commit this file — see [Secrets](#secrets--configuration) below).
   The first PDF upload will open a browser consent flow and cache a
   `token.json` for subsequent runs.
3. **Ollama**: `ollama pull llama3.2:3b` (or whatever model you set as
   `LLM_MODEL` in `.env`).

---

## Design Decisions

See [DECISIONS.md](DECISIONS.md) for the full rationale behind the scraping
schema, incremental ingestion strategy, chunking approach, and chat/RAG design.