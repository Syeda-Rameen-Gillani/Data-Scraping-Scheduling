import os
import json
import hashlib

from chunker import chunk_text
from weaviate_client import get_client
from sentence_transformers import SentenceTransformer
from weaviate.classes.query import Filter
from dotenv import load_dotenv

load_dotenv()

JSON_DIR = "json"
MANIFEST_PATH = "output/ingestion_manifest.json"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

model = SentenceTransformer(EMBEDDING_MODEL)


def get_chunk_id(file_name: str, chunk_index: int, text: str) -> str:
    """Stable ID for a chunk, based on judgment + position + content."""
    raw = f"{file_name}_{chunk_index}_{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint(record: dict, text: str) -> str:
    """
    Hash the judgment's text together with the fields that Section 11's
    citation-update path can change (Case Number, citation_year, journal,
    page_number). A citation update leaves the text identical, so hashing
    text alone would cause it to be silently skipped here even though the
    metadata changed in S3/MongoDB. Including the citation fields ensures
    a citation change is detected and triggers re-ingestion.
    """
    fingerprint_source = "|".join([
        text,
        str(record.get("Case Number")),
        str(record.get("citation_year")),
        str(record.get("citation_journal")),
        str(record.get("citation_page_number")),
    ])
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


def _delete_existing_chunks(collection, file_name: str) -> None:
    """
    Remove previously-ingested chunks for this judgment before re-inserting
    (e.g. after a citation update changes the metadata JSON).
    """
    collection.data.delete_many(
        where=Filter.by_property("file_name").equal(file_name)
    )


def _build_properties(record: dict, file_name: str, chunk: str, chunk_index: int, chunk_id: str) -> dict:
    """
    Maps the new 33-field metadata schema (Section 4) onto the Weaviate
    property names declared in create_collection.py. Fields with spaces/
    parens in the JSON schema (e.g. "Judge Name(s)") get safe property names.
    """
    return {
        "text": chunk,
        "chunk_index": chunk_index,
        "chunk_id": chunk_id,

        "file_name": file_name,
        "case_title": record.get("Case Title"),
        "case_number": record.get("Case Number"),
        "court_name": record.get("Court Name"),
        "reference_url": record.get("reference_url"),

        "judge_names": record.get("Judge Name(s)"),
        "case_category": record.get("case_category"),
        "disposition_type": record.get("disposition_type"),
        "final_decision": record.get("final_decision"),
        "petitioner_appellant": record.get("petitioner_appellant"),
        "respondent": record.get("respondent"),
        "high_court_decision_date": record.get("high_court_decision_date"),
        "legal_keywords": record.get("legal_keywords") or [],
        "statutes_mentioned": record.get("statutes_mentioned") or [],
        "precedents_cited": record.get("precedents_cited") or [],
    }


def ingest():
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    manifest = _load_manifest()

    new_cases = 0
    updated_cases = 0
    unchanged_cases = 0
    missing_content_count = 0
    new_chunk_count = 0

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
            print(f"Skipping {filename}: no fileName in metadata.")
            missing_content_count += 1
            continue

        if not text:
            print(f"Skipping {file_name}: no content in metadata JSON.")
            missing_content_count += 1
            continue

        content_hash = _fingerprint(record, text)

        # Cheap local check first -- unchanged content means no re-chunking,
        # no re-embedding, no Weaviate round trip at all.
        if manifest.get(file_name) == content_hash:
            unchanged_cases += 1
            continue

        is_update = file_name in manifest
        if is_update:
            _delete_existing_chunks(collection, file_name)
            updated_cases += 1
        else:
            new_cases += 1

        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            chunk_id = get_chunk_id(file_name, i, chunk)
            vector = model.encode(chunk).tolist()

            collection.data.insert(
                properties=_build_properties(record, file_name, chunk, i, chunk_id),
                vector=vector,
            )
            new_chunk_count += 1

        manifest[file_name] = content_hash

    _save_manifest(manifest)

    print(f"New cases ingested: {new_cases}")
    print(f"Updated cases re-ingested: {updated_cases}")
    print(f"Unchanged cases skipped (no Weaviate calls made): {unchanged_cases}")
    print(f"Cases skipped (missing fileName/content): {missing_content_count}")
    print(f"Total new chunks inserted: {new_chunk_count}")

    client.close()


if __name__ == "__main__":
    ingest()