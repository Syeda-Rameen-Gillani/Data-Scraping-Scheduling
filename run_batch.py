"""
run_batch.py

Processes cases until TARGET_NEW judgments have been successfully added to
state (not just attempted) -- since roughly half of listing rows have no
PDF at all, capping by raw attempt count under-delivers on real new data.
"""

from scraper import scrape_cases, process_case
import s3_utils

TARGET_NEW = 25

state = s3_utils.download_state_file()
print(f"Starting state: {len(state)} judgment(s) already processed.")

cases = scrape_cases(max_pages=1)
todo = [c for c in cases if c.get("code") not in state]
print(f"{len(todo)} case(s) not yet in state to try.")

successes = 0
attempted = 0

for case in todo:
    if successes >= TARGET_NEW:
        break

    attempted += 1
    before = dict(state)
    process_case(case, state)

    if state != before:
        s3_utils.upload_state_file(state)
        successes += 1
        print(f"[success {successes}/{TARGET_NEW}] (attempt {attempted}) {case.get('code')}")
    else:
        print(f"[skipped] (attempt {attempted}) {case.get('code')} -- no PDF or failed")

print(f"\nDone. {successes} new judgment(s) added (out of {attempted} attempted).")
print(f"State now has {len(state)} entries total.")