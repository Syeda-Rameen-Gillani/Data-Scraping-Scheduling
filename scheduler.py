import logging
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from scraper import scrape_cases
from storage import upsert

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def daily_scrape_job():
    """
    Scheduled job: scrape ALL available pages (no hard cap), then upsert
    into the master store.

    max_pages is intentionally omitted so scrape_cases() defaults to None,
    meaning it keeps paginating until the site returns an empty page.
    If you need to cap pages during testing, set MAX_PAGES env var.
    """
    log.info("=" * 50)
    log.info("Scrape job STARTING")
    try:
        # Read an optional env-var cap (useful for smoke-testing without
        # scraping the entire site).  In production this will be unset,
        # so max_pages stays None and all pages are fetched.
        max_pages_env = os.getenv("MAX_PAGES")
        max_pages = int(max_pages_env) if max_pages_env else None

        records = scrape_cases(max_pages=max_pages)
        log.info("Got %d records.", len(records))

        if records:
            summary = upsert(records)
            log.info("Done: %s", summary)
        else:
            log.warning("No records returned — site may be down or empty.")

    except Exception as exc:
        log.exception("Unhandled error in scrape job: %s", exc)

    log.info("Scrape job DONE")
    log.info("=" * 50)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Karachi")
    scheduler.add_job(
        daily_scrape_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="shc_daily_scrape",
        max_instances=1,    # prevents overlap if a run takes longer than 24 h
        coalesce=True,      # if the process was down, run once on restart, not N times
        misfire_grace_time=3600,  # tolerate up to 1 h of clock drift / downtime
    )
    log.info("Scheduler running. Fires daily at 02:00 Karachi time. Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped cleanly.")