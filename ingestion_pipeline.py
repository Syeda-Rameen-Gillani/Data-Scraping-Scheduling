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


def get_chunk_id(case_code: str, chunk_index: int, text: str) -> str:
    """Stable ID for a chunk, based on case + position + content."""
    raw = f"{case_code}_{chunk_index}_{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest() -> dict:
    """
    Local record of what's already been ingested: {case_code: content_hash}.

    This is the source of truth for "have I already embedded this case's
    current content?" so a run never has to scan Weaviate to find out.
    Lookups stay O(1) regardless of how large the Weaviate collection gets,
    which is what keeps daily ingestion from slowing down as data accumulates.
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
    os.replace(tmp, MANIFEST_PATH)  # atomic swap, same pattern as storage.py


def _delete_existing_chunks(collection, case_code: str) -> None:
    """
    Remove any previously-ingested chunks for this case before re-inserting
    updated content. Without this, an edited judgment would leave its old
    (now-stale) chunks sitting in Weaviate alongside the new ones.
    """
    collection.data.delete_many(
        where=Filter.by_property("case_code").equal(case_code)
    )


def ingest():
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    manifest = _load_manifest()

    new_cases = 0
    updated_cases = 0
    unchanged_cases = 0
    missing_md_count = 0
    new_chunk_count = 0

    for filename in os.listdir(JSON_DIR):
        if not filename.endswith(".json"):
            continue

        json_path = os.path.join(JSON_DIR, filename)
        with open(json_path, "r", encoding="utf-8") as f:
            record = json.load(f)

        case_code = record.get("code")
        local_markdown = record.get("local_markdown")

        if not local_markdown or not os.path.exists(local_markdown):
            print(f"Skipping {case_code}: markdown file not found ({local_markdown}).")
            missing_md_count += 1
            continue

        with open(local_markdown, "r", encoding="utf-8") as f:
            text = f.read()

        content_hash = _content_hash(text)

        # Cheap local check first -- if the content hasn't changed since the
        # last run, skip the case entirely: no re-chunking, no re-embedding,
        # no Weaviate round trip at all.
        if manifest.get(case_code) == content_hash:
            unchanged_cases += 1
            continue

        is_update = case_code in manifest
        if is_update:
            _delete_existing_chunks(collection, case_code)
            updated_cases += 1
        else:
            new_cases += 1

        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            chunk_id = get_chunk_id(case_code, i, chunk)
            vector = model.encode(chunk).tolist()

            collection.data.insert(
                properties={
                    "text": chunk,
                    "case_code": case_code,
                    "case_no": record.get("case_no"),
                    "citation": record.get("citation"),
                    "topic": record.get("topic"),
                    "pdf_url": record.get("pdf_url"),
                    "chunk_index": i,
                    "chunk_id": chunk_id,
                },
                vector=vector,
            )
            new_chunk_count += 1

        manifest[case_code] = content_hash

    _save_manifest(manifest)

    print(f"New cases ingested: {new_cases}")
    print(f"Updated cases re-ingested: {updated_cases}")
    print(f"Unchanged cases skipped (no Weaviate calls made): {unchanged_cases}")
    print(f"Cases skipped (missing markdown): {missing_md_count}")
    print(f"Total new chunks inserted: {new_chunk_count}")

    client.close()


if __name__ == "__main__":
    ingest()
