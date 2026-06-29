import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MASTER_FILE = Path("output/cases_master.json")
RUNS_DIR    = Path("output/runs")


def _load_master() -> dict:
    """
    Load the master JSON file and return a dict keyed by case code.
    Returns an empty dict if the file does not exist or is corrupt.
    """
    if not MASTER_FILE.exists():
        return {}
    try:
        with MASTER_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return {rec["code"]: rec for rec in data if rec.get("code")}
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Master file corrupt (%s) — starting fresh.", exc)
        return {}


def _save_master(store: dict) -> None:
    """
    Atomically write *store* to MASTER_FILE.

    Writes to a .tmp sibling first, then renames — so a crash mid-write
    never leaves a partial / corrupt master file on disk.
    """
    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MASTER_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(list(store.values()), fh, indent=2, ensure_ascii=False)
    tmp.replace(MASTER_FILE)


def _save_run_snapshot(records: list, timestamp: str) -> Path:
    """Write the records from a single run to a timestamped snapshot file."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"run_{timestamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    return path


def upsert(records: list[dict]) -> dict:
    """
    Merge *records* into the master store (idempotent upsert).

    Rules
    -----
    - A record with no 'code' is silently skipped.
    - New code  → inserted.
    - Existing code, data changed  → updated.
    - Existing code, data unchanged → left as-is (counter incremented).

    The '_scraped_at' timestamp is intentionally excluded from the change
    comparison so that re-scraping identical data does not count as an update.

    The original *records* list is never mutated.

    Returns a summary dict:
        added      : int
        updated    : int
        unchanged  : int
        total      : int   — total records in the master store after the run
        snapshot   : str   — path to the per-run snapshot file
        timestamp  : str   — ISO-8601 UTC timestamp of this run
    """
    store     = _load_master()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    added = updated = unchanged = 0
    stamped_records = []           # what goes into the snapshot

    for rec in records:
        code = rec.get("code")
        if not code:
            continue

        # Work on a copy so the caller's list is never mutated
        stamped = {**rec, "_scraped_at": timestamp}
        stamped_records.append(stamped)

        if code not in store:
            store[code] = stamped
            added += 1
        else:
            existing = store[code]

            # Compare data fields only — ignore _scraped_at on both sides
            def _data(r):
                return {k: v for k, v in r.items() if k != "_scraped_at"}

            if _data(existing) != _data(stamped):
                store[code] = stamped
                updated += 1
            else:
                unchanged += 1

    _save_master(store)
    snapshot_path = _save_run_snapshot(stamped_records, timestamp)

    summary = {
        "added":     added,
        "updated":   updated,
        "unchanged": unchanged,
        "total":     len(store),
        "snapshot":  str(snapshot_path),
        "timestamp": timestamp,
    }

    log.info("Storage upsert: %s", summary)
    return summary