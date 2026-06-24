import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MASTER_FILE = Path("output/cases_master.json")
RUNS_DIR    = Path("output/runs")


def _load_master():
    if not MASTER_FILE.exists():
        return {}
    try:
        with MASTER_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return {rec["code"]: rec for rec in data if rec.get("code")}
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Master file corrupt (%s) — starting fresh.", exc)
        return {}


def _save_master(store):
    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MASTER_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(list(store.values()), fh, indent=2, ensure_ascii=False)
    tmp.replace(MASTER_FILE)


def _save_run_snapshot(records, timestamp):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"run_{timestamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    return path

def upsert(records):
    store = _load_master()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    added = updated = unchanged = 0

    for rec in records:
        code = rec.get("code")
        if not code:
            continue

        rec["_scraped_at"] = timestamp

        if code not in store:
            store[code] = rec
            added += 1
        else:
            existing = store[code]

            old_compare = existing.copy()
            new_compare = rec.copy()

            old_compare.pop("_scraped_at", None)
            new_compare.pop("_scraped_at", None)

            if old_compare != new_compare:
                store[code] = rec
                updated += 1
            else:
                unchanged += 1

    _save_master(store)
    snapshot_path = _save_run_snapshot(records, timestamp)

    summary = {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "total": len(store),
        "snapshot": str(snapshot_path),
        "timestamp": timestamp,
    }

    log.info("Storage upsert: %s", summary)
    return summary