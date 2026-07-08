# Case Law Scraper & RAG Service — Sindh High Court

Scrapes case records from the [SHC Case Law portal](https://caselaw.shc.gov.pk/caselaw/search-all/search),
downloads and archives the underlying judgment PDFs, converts them to markdown,
ingests them into a Weaviate vector store, and exposes a FastAPI chat endpoint
that answers questions with citations back to the source case.

---

## Project Structure

.
├── scraper.py
├── storage.py
├── scheduler.py
├── pdf_pipeline.py
├── s3_utils.py                  # Uploads PDFs to Amazon S3 and returns the object URL
├── chunker.py
├── ingestion_pipeline.py
├── weaviate_client.py
├── create_collection.py
├── retrieval.py                 # Vector, hybrid and reranked retrieval
├── reranking.py                 # Cross-encoder reranker
├── classification.py            # Query classifier
├── generation.py                # LLM answer generation
├── evaluate.py                  # Retrieval evaluation
├── evaluate_classification.py   # Query-classification evaluation
├── eval_set.py                  # Self-authored evaluation dataset
├── app.py                       # FastAPI API
├── docker-compose.yml
├── test_scraper.py
├── DECISIONS.md
├── evaluation_results/          # Evaluation outputs
├── logs/
├── output/
├── json/
├── markdown/
└── pdfs/

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
    process_case(case)

print(summary)
"

python ingestion_pipeline.py
```

Only new or modified cases are embedded into Weaviate using the incremental ingestion manifest.

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

### Serving the API

```bash
uvicorn app:app --reload
```

Available endpoints:

- `GET /health`

  Returns the service health status.

- `GET /chat?q=...`

  Performs the complete RAG pipeline:

  1. Query classification
  2. Exact case-number lookup (when applicable)
  3. Vector retrieval
  4. LLM answer generation

  The classifier first labels each query as:

  - relevant
  - other (legal but outside this corpus)
  - irrelevant

  Queries classified as `other` or `irrelevant` are declined without running retrieval.

  Example:

```bash
curl "http://localhost:8000/chat?q=What happened in Adm. Suit 1088/2005?"
```

## Advanced Retrieval

Stage 3 extends the retrieval pipeline with three independent retrieval improvements.

### Vector Search

Sentence-transformers embeddings (`all-MiniLM-L6-v2`) are used to retrieve the most semantically similar judgment chunks.

---

### Exact Metadata Lookup

Queries containing a case number (e.g. `68/2013`) bypass semantic retrieval entirely and perform an exact metadata lookup.

---

### Cross-Encoder Reranking

The top vector-search candidates are reranked using a cross-encoder model before selecting the final Top-K results.

This improves ordering when several retrieved chunks are semantically similar.

---

### Hybrid Search

Hybrid retrieval combines

- BM25 keyword matching
- semantic vector similarity

using Weaviate's native hybrid search.

Both retrieval methods can be evaluated independently.

---

### Query Classification

Incoming questions are classified as

- relevant
- other
- irrelevant

before retrieval.

Off-domain questions are rejected early instead of wasting retrieval and LLM inference.


## Evaluation

A manually authored evaluation dataset (`eval_set.py`) containing both in-domain and off-domain questions is included.

Evaluation scripts:

```bash
python evaluate.py
```

Evaluates:

- baseline vector retrieval
- reranked retrieval
- hybrid retrieval

and reports:

- Hit Rate@K
- Mean Reciprocal Rank (MRR)

---

```bash
python evaluate_classification.py
```

Evaluates the query classifier and reports:

- Accuracy
- False Positives
- False Negatives
- Per-question predictions

Evaluation outputs are automatically written to

```
evaluation_results/
```


## Running Tests

Scraper tests:

```bash
pytest test_scraper.py -v
```

Retrieval evaluation:

```bash
python evaluate.py
```

Classification evaluation:

```bash
python evaluate_classification.py
```

The retrieval evaluation reports:

- Hit Rate
- MRR

The classification evaluation reports:

- Accuracy
- False Positives
- False Negatives

## Output layout

output/
    cases_master.json
    runs/
    ingestion_manifest.json

json/
markdown/
pdfs/

evaluation_results/
    eval_<timestamp>.json
    classifier_eval_<timestamp>.json

logs/

## Environment variables

Copy `.env.example` to `.env` and fill in your real values:

​```bash
cp .env.example .env
​```

| Variable | Purpose | Required? |
|---|---|---|
| Variable                    | Purpose                                                                       | Required?                           |
| --------------------------- | ----------------------------------------------------------------------------- | ----------------------------------- |
| `AWS_ACCESS_KEY_ID`         | AWS access key used to authenticate with Amazon S3                            | Yes                                 |
| `AWS_SECRET_ACCESS_KEY`     | AWS secret access key                                                         | Yes                                 |
| `AWS_REGION`                | AWS region where the S3 bucket is hosted                                      | Yes                                 |
| `S3_BUCKET_NAME`            | Amazon S3 bucket used to store downloaded judgment PDFs                       | Yes                                 |
| `EXTERNAL_JUDGMENT_API_KEY` | API key used to access the external judgment metadata service (if applicable) | Yes                                 |
| `EMBEDDING_MODEL`           | Sentence Transformers model used for document and query embeddings            | No (defaults to `all-MiniLM-L6-v2`) |
| `LLM_MODEL`                 | Ollama model used for answer generation                                       | No (defaults to `llama3.2:3b`)      |
| `WEAVIATE_COLLECTION`       | Weaviate collection name                                                      | No (defaults to `CaseChunk`)        |
| `TOP_K`                     | Number of retrieved chunks returned for each query                            | No (defaults to `5`)                |


## Secrets & Configuration

The following files and credentials should never be committed:

- `.env`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `EXTERNAL_JUDGMENT_API_KEY`

Judgment PDFs are stored in Amazon S3. AWS credentials are loaded from environment variables.

Weaviate currently runs with anonymous access enabled for local development only.

  ## One-time Setup

Before running the project, configure your `.env` file with the required AWS credentials and application settings.

1. **Start Weaviate**

```bash
docker compose up -d
python create_collection.py
```

2. **Configure Amazon S3**

Add the following variables to your `.env` file:

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION
S3_BUCKET_NAME
```

Downloaded judgment PDFs will automatically be uploaded to the configured Amazon S3 bucket.

3. **Configure the External Judgment API**

Add:

```
EXTERNAL_JUDGMENT_API_KEY
```

to your `.env` file if required by the metadata service.

4. **Install Ollama**

```bash
ollama pull llama3.2:3b
```

(or whichever model you configured as `LLM_MODEL`.)

---

## Design Decisions

See `DECISIONS.md` for detailed rationale covering:

- scraper architecture
- metadata extraction
- incremental ingestion
- chunking strategy
- vector retrieval
- cross-encoder reranking
- hybrid retrieval
- query classification
- evaluation methodology
- observed failure modes
- lessons learned