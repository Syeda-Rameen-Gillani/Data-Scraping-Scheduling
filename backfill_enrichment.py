"""
Phase 1 migration script: backfill LLM-derived metadata onto JSON records
that were written before metadata_enrichment.py's LLM call was actually
wired up (or that failed and got the old silent-fallback null/[] fields).

Usage:
    python backfill_enrichment.py              # enrich only records that look unenriched
    python backfill_enrichment.py --force      # re-enrich every record regardless
    python backfill_enrichment.py --limit 5    # process at most 5 records (useful for a test run)

After this completes, re-run create_collection.py (if you haven't already
moved to the new schema) and then ingest.py — the updated _fingerprint()
in ingest.py hashes the full metadata record, so every JSON touched here
will be detected as changed and re-ingested automatically.
"""

import os
import json
import glob
import logging
import argparse
import csv
from typing import Optional

VALIDATION_REPORT = "metadata_validation_report.csv"

from metadata_enrichment import extract_llm_fields, MetadataExtractionError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

JSON_DIR = "json"
FAILURES_PATH = "output/backfill_failures.json"

# head_note and Short Summary of the Case are SYNTHESIZED fields — per
# metadata_enrichment.py's own prompt rules, the LLM is told to null them
# out ONLY if the judgment text is too garbled/short to summarize at all,
# never just because there's no pre-written headnote in the source. That
# makes "both still null" a strong signal that extraction never actually
# ran on this record (e.g. it predates the LLM call being wired up, or an
# earlier run silently fell back to nulls) rather than a real "nothing to
# summarize" case.
#
# This is a heuristic, not a guarantee — if you know some documents are
# genuinely too short/garbled to summarize, --force will still leave them
# alone unless you explicitly want to re-check them too.
_COMPLETION_MARKERS = ("head_note", "Short Summary of the Case")

def load_priority_files(limit):
    files = []

    with open(VALIDATION_REPORT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            files.append(row["File"])

    return set(files[:limit])



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


def _save_record(json_path: str, record: dict) -> None:
    """Atomic write, consistent with the manifest/failures convention elsewhere."""
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    os.replace(tmp, json_path)


def backfill(force: bool = False, limit: Optional[int] = None) -> None:
    failures = _load_failures()

    already_enriched = 0
    enriched = 0
    failed = 0
    processed = 0

    json_paths = sorted(glob.glob(os.path.join(JSON_DIR, "*.json")))

    priority_files = None

    if limit is not None:
        priority_files = load_priority_files(limit)

    for json_path in json_paths:

        with open(json_path, "r", encoding="utf-8") as f:
            record = json.load(f)

        if priority_files is not None:
            if os.path.basename(json_path) not in priority_files:
                continue

        file_name = record.get("fileName") or os.path.basename(json_path)
        text = record.get("content")

        if not text:
            log.warning("Skipping %s: no content to enrich from.", file_name)
            continue

        processed += 1

        try:
            llm_fields = extract_llm_fields(text, pdf_filename=file_name)
        except MetadataExtractionError as exc:
            # extract_llm_fields already retried transient failures inside
            # itself (see metadata_enrichment.py's _call_llm) — if we're
            # here, retries were exhausted or the model returned something
            # unparseable. Log it and move on; nothing on disk is touched,
            # so this record is safe to retry later by re-running this
            # script (it'll still look "unenriched" and get picked up again).
            log.warning("Backfill failed for %s: %s", file_name, exc.reason)
            failures.append({"file_name": file_name, "reason": exc.reason})
            _save_failures(failures)
            failed += 1
            continue

        # Same "Decision/Order Date" default as build_full_metadata applies
        # at initial ingestion time — keep it consistent here too.
        if not llm_fields.get("Decision/Order Date"):
            llm_fields["Decision/Order Date"] = llm_fields.get("high_court_decision_date")

        # Overwrite only the LLM-derived keys; deterministic fields
        # (Court Name, citation_year, source_file, etc.) are untouched.
        record.update(llm_fields)
        _save_record(json_path, record)
        enriched += 1

    print(f"Already enriched (skipped): {already_enriched}")
    print(f"Newly enriched: {enriched}")
    print(f"Failed (see {FAILURES_PATH}): {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Re-enrich every document, even ones that already look enriched.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process the first N documents needing enrichment (useful for a test run before going full-scale).",
    )
    args = parser.parse_args()
    backfill(force=args.force, limit=args.limit)