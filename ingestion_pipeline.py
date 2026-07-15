import os
import json
import hashlib
import logging

from chunker import chunk_text
from weaviate_client import get_client
from sentence_transformers import SentenceTransformer
from weaviate.classes.query import Filter
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

JSON_DIR = "json"
MANIFEST_PATH = "output/ingestion_manifest.json"
FAILURES_PATH = "output/ingestion_failures.json"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

model = SentenceTransformer(EMBEDDING_MODEL)


def get_chunk_id(file_name: str, chunk_index: int, text: str) -> str:
    """Stable ID for a chunk, based on judgment + position + content."""
    raw = f"{file_name}_{chunk_index}_{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint(record: dict, text: str) -> str:
    """
    Hash the judgment's text together with a canonical snapshot of ALL
    other metadata fields on the record (not a hand-picked subset).

    Originally this only hashed the citation_* fields alongside text,
    specifically to catch Section 11's citation-update path. But that
    approach requires remembering to add every new field that might
    change later — it already missed the LLM-backfill-enrichment case
    (judge_names, head_note, statutes_mentioned, etc. changing without
    the citation fields changing), and it will miss the next one too.
    Hashing the full record removes that maintenance burden: ANY change
    to ANY metadata field — a citation update, a backfill enrichment run,
    a manual correction — changes the hash and triggers re-ingestion.

    "content" is excluded from the snapshot because `text` already covers
    it (and record["content"] IS text — hashing it twice is redundant).
    "source_file"/"fileName" are excluded because they're identifiers,
    not content — a filename shouldn't be able to trigger a re-ingest.
    """
    metadata_snapshot = {
        k: v for k, v in record.items()
        if k not in ("content", "source_file", "fileName")
    }
    fingerprint_source = text + "|" + json.dumps(metadata_snapshot, sort_keys=True, default=str)
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()


def _load_manifest() -> dict:
    """
    Local record of what's already been ingested: {file_name: content_hash}.
    Same O(1) lookup pattern as Stage 2 — avoids scanning Weaviate to find
    out whether a judgment's current content has already been embedded.
    """
    if not os.path.exists(MANIFEST_PATH):
        return {}
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(manifest: dict) -> None:
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, MANIFEST_PATH)  # atomic swap


def _load_failures() -> list:
    if not os.path.exists(FAILURES_PATH):
        return []
    with open(FAILURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_failures(failures: list) -> None:
    os.makedirs(os.path.dirname(FAILURES_PATH), exist_ok=True)
    tmp = FAILURES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2)
    os.replace(tmp, FAILURES_PATH)


def _delete_existing_chunks(collection, file_name: str) -> None:
    """
    Remove previously-ingested chunks for this judgment before re-inserting
    (e.g. after a citation update changes the metadata JSON).
    """
    collection.data.delete_many(
        where=Filter.by_property("file_name").equal(file_name)
    )


# --------------------------------------------------------------------------
# Property mapping
# --------------------------------------------------------------------------
# NOTE: this maps (nearly) all 33 metadata fields onto Weaviate property
# names. Two fields are deliberately EXCLUDED:
#   - "content": the full raw judgment text. The chunk's own "text" property
#     already covers this in pieces; duplicating the entire judgment onto
#     every single chunk record would massively bloat storage for no
#     retrieval benefit.
#   - "source_file": redundant with file_name (same value plus ".pdf").
#
# IMPORTANT: these property names must match what create_collection.py
# actually declared on the collection, or Weaviate will either reject the
# insert or silently drop unrecognized properties depending on your schema
# config. Please share create_collection.py so this can be double-checked
# — I'm inferring names from the existing snake_case convention
# (judge_names, case_category, etc.) already used in this file.
def _build_properties(record: dict, file_name: str, chunk: str, chunk_index: int, chunk_id: str) -> dict:
    return {
        "text": chunk,
        "chunk_index": chunk_index,
        "chunk_id": chunk_id,

        "file_name": file_name,
        "page_count": record.get("Page count"),
        "court_name": record.get("Court Name"),
        "court_type": record.get("courtType"),
        "case_title": record.get("Case Title"),
        "case_number": record.get("Case Number"),

        "type_of_petition": record.get("Type of Petition or Application"),
        "case_category": record.get("case_category"),
        "disposition_type": record.get("disposition_type"),
        "bench_strength": record.get("bench_strength"),

        "citation_year": record.get("citation_year"),
        "citation_journal": record.get("citation_journal"),
        "citation_page_number": record.get("citation_page_number"),

        "case_filing_date": record.get("case_filing_date"),
        "trial_court_decision_date": record.get("trial_court_decision_date"),
        "appellate_court_decision_date": record.get("appellate_court_decision_date"),
        "high_court_decision_date": record.get("high_court_decision_date"),
        "supreme_court_decision_date": record.get("supreme_court_decision_date"),
        "hearing_date": record.get("Hearing Date"),
        "decision_order_date": record.get("Decision/Order Date"),

        "petitioner_appellant": record.get("petitioner_appellant"),
        "respondent": record.get("respondent"),
        "applicant_and_respondents": record.get("Applicant and Respondents"),
        "advocate_names": record.get("Advocate Names for each party"),
        "judge_names": record.get("Judge Name(s)"),

        "fir_number_and_date": record.get("FIR Number and Date"),
        "legal_sections_involved": record.get("Legal Sections Involved"),
        "articles_sections_cited": record.get("articles_sections_cited") or [],
        "statutes_mentioned": record.get("statutes_mentioned") or [],
        "key_legal_issues": record.get("key_legal_issues") or [],

        "head_note": record.get("head_note"),
        "cited_case_laws": record.get("Cited Case Laws"),
        "precedents_cited": record.get("precedents_cited") or [],
        "short_summary": record.get("Short Summary of the Case"),
        "legal_keywords": record.get("legal_keywords") or [],
        "final_decision": record.get("final_decision"),

        "reference_url": record.get("reference_url"),
        "source_url": record.get("source_url"),
    }


def _process_case(collection, manifest: dict, record: dict, file_name: str, text: str) -> tuple[str, int]:
    """
    Handles one judgment end-to-end: chunk, embed, (delete old + insert new),
    return (status, chunk_count). Chunking and embedding happen BEFORE any
    deletion, so a failure here never destroys already-ingested chunks —
    the judgment simply stays in its previous good state until retried.
    Raises on failure; caller is responsible for catching and logging.
    """
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("chunk_text() returned no chunks for non-empty content")

    # Compute all chunk_id + vector pairs BEFORE touching Weaviate at all.
    prepared = []
    for i, chunk in enumerate(chunks):
        chunk_id = get_chunk_id(file_name, i, chunk)
        vector = model.encode(chunk).tolist()
        prepared.append((i, chunk, chunk_id, vector))

    is_update = file_name in manifest
    if is_update:
        _delete_existing_chunks(collection, file_name)

    for i, chunk, chunk_id, vector in prepared:
        collection.data.insert(
            properties=_build_properties(record, file_name, chunk, i, chunk_id),
            vector=vector,
        )

    return ("updated" if is_update else "new"), len(prepared)


def ingest():
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    manifest = _load_manifest()
    failures = _load_failures()

    new_cases = 0
    updated_cases = 0
    unchanged_cases = 0
    missing_content_count = 0
    failed_count = 0
    new_chunk_count = 0

    try:
        for filename in os.listdir(JSON_DIR):
            if not filename.endswith(".json"):
                continue

            json_path = os.path.join(JSON_DIR, filename)
            with open(json_path, "r", encoding="utf-8") as f:
                record = json.load(f)

            # fileName is the stable per-judgment identifier in the new schema
            # (replaces the old flat scraper's "code" field).
            file_name = record.get("fileName")
            text = record.get("content")

            if not file_name:
                log.warning("Skipping %s: no fileName in metadata.", filename)
                missing_content_count += 1
                continue

            if not text:
                log.warning("Skipping %s: no content in metadata JSON.", file_name)
                missing_content_count += 1
                continue

            content_hash = _fingerprint(record, text)

            # Cheap local check first -- unchanged content means no
            # re-chunking, no re-embedding, no Weaviate round trip at all.
            if manifest.get(file_name) == content_hash:
                unchanged_cases += 1
                continue

            try:
                status, chunk_count = _process_case(collection, manifest, record, file_name, text)
            except Exception as exc:
                log.warning("Failed to ingest %s: %s", file_name, exc)
                failures.append({"file_name": file_name, "reason": str(exc)})
                failed_count += 1
                continue

            if status == "new":
                new_cases += 1
            else:
                updated_cases += 1
            new_chunk_count += chunk_count

            # Persist immediately after each successful case — interrupt-safe,
            # matching the scraper's per-judgment state-save pattern. If the
            # script dies on the next document, everything processed so far
            # is already durably recorded and won't be re-ingested/duplicated.
            manifest[file_name] = content_hash
            _save_manifest(manifest)
            _save_failures(failures)

    finally:
        # Belt-and-suspenders: persist whatever we have even if the loop
        # above raised something unexpected (e.g. os.listdir failure mid-way
        # isn't really recoverable, but a partial manifest is still correct).
        _save_manifest(manifest)
        _save_failures(failures)
        client.close()

    print(f"New cases ingested: {new_cases}")
    print(f"Updated cases re-ingested: {updated_cases}")
    print(f"Unchanged cases skipped (no Weaviate calls made): {unchanged_cases}")
    print(f"Cases skipped (missing fileName/content): {missing_content_count}")
    print(f"Cases failed (see {FAILURES_PATH}): {failed_count}")
    print(f"Total new chunks inserted: {new_chunk_count}")


if __name__ == "__main__":
    ingest()