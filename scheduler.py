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
    log.info("=" * 50)
    log.info("Scrape job STARTING")
    try:
        records = scrape_cases(max_pages=5)
        log.info("Got %d records.", len(records))
        if records:
            summary = upsert(records)
            log.info("Done: %s", summary)
        else:
            log.warning("No records returned.")
    except Exception as exc:
        log.exception("Unhandled error: %s", exc)
    log.info("Scrape job DONE")
    log.info("=" * 50)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Karachi")
    scheduler.add_job(
        daily_scrape_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="shc_daily_scrape",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    log.info("Scheduler running. Fires daily at 02:00 Karachi time. Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Stopped.")