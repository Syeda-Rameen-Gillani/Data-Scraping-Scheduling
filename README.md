# Case Law Scraper (SHC)

This project scrapes case law data from the Sindh High Court Case Law portal and stores it locally in structured JSON format. It supports both manual execution and automated scheduled scraping.

---

## 📁 Project Structure

.
├── scraper.py          # Scraping logic (requests + parsing)
├── storage.py          # Data storage + upsert logic
├── scheduler.py        # Scheduler entry point (optional)
├── logs/               # Log files (auto-created)
├── output/             # Stored JSON data (auto-created)
│   ├── cases_master.json
│   └── runs/
└── README.md

---

## ⚙️ Features

- Scrapes case records from SHC portal
- Handles retries and throttling
- Parses HTML table data
- Deduplicates records using case `code`
- Maintains:
  - Master dataset (`cases_master.json`)
  - Run-wise snapshots (`output/runs/`)
- Logging to console and files
- Optional daily scheduler (02:00 AM Asia/Karachi)

---

## 🧰 Requirements

- Python 3.8+
- Recommended: virtual environment

### Install dependencies

```bash
pip install requests beautifulsoup4 apscheduler
````

---

## 🚀 Run Without Scheduler (Manual Run)

Run scraping manually using:

```bash
python -c "from scraper import scrape_cases; from storage import upsert; print(upsert(scrape_cases(max_pages=5)))"
```

### What happens:

* Scrapes up to 5 pages
* Stores results in `output/cases_master.json`
* Saves snapshot in `output/runs/`
* Prints summary (added/updated/unchanged)

---

## ⏰ Run With Scheduler (Automated Daily Run)

The scheduler runs the scraper every day at **02:00 AM (Asia/Karachi time)**.

### Start scheduler:

```bash
python scheduler.py
```

### Expected output:

Scheduler running. Fires daily at 02:00 Karachi time. Ctrl+C to stop.

### Stop scheduler:

Press:

CTRL + C

---

## 📊 Output Files

### Master Data

output/cases_master.json

Contains the latest deduplicated dataset.

### Run Snapshots

output/runs/run_YYYY-MM-DDTHH-MM-SSZ.json

Stores raw results from each run for history/debugging.

---

## 🪵 Logs

logs/scraper.log   → scraping logs
logs/scheduler.log → scheduler logs

Logs also appear in terminal.

---

## ⚠️ Notes

* Uses retry mechanism for failed requests
* Adds delay between requests (throttling = 2 seconds)
* Respects robots.txt where applicable
* If website structure changes, parser may need updates
* Default scraping depth: 5 pages

---

## 🛠 Configuration

You can modify these in scraper.py:

REQUEST_TIMEOUT = 20
RETRY_LIMIT = 3
RETRY_BACKOFF = 5
THROTTLE = 2

Scheduler timing (in scheduler.py):

CronTrigger(hour=2, minute=0)

---

## 🧑‍💻 Author

Custom scraping system for legal research and case tracking.


