# Case Law Scraper – Design Decisions

## 1. Data Source
Data is extracted from:
https://caselaw.shc.gov.pk/caselaw/search-all/search

The site uses an AJAX backend endpoint:
https://caselaw.shc.gov.pk/caselaw/AJAX_PUBLIC.php

The scraper directly interacts with this endpoint instead of scraping static pages.

---

## 2. Scraping Approach
The scraper sends POST requests using Python `requests`.

The response is JSON, where the main data is embedded as HTML inside the `msg` field.

BeautifulSoup is used to parse the HTML table and extract structured case data.

Code is organized into modules:
- scraper.py → data collection
- storage.py → persistence + deduplication
- scheduler.py → automation

---

## 3. Data Schema
Each record has the following structure:

- code (string): Unique case identifier
- s_no (string): Serial number
- citation (string or null): Case citation
- topic (string or null): Legal topic
- case_no (string or null): Case reference number
- detail_url (string or null): Link to case details
- _scraped_at (string): UTC timestamp of scraping

All fields are always present; missing values are stored as null.

---

## 4. Failure Handling
The system handles failures using:

- Request timeouts to prevent hanging
- Retry mechanism (up to 3 attempts)
- Backoff delays between retries
- Safe handling of JSON and parsing errors
- Empty results returned instead of crashing
- Scheduler-level exception handling

This ensures continuous operation without manual intervention.

---

## 5. Deduplication / Idempotency
Deduplication is implemented using the `code` field.

- New records are inserted if code does not exist
- Existing records are compared (excluding timestamp)
- Only changed records are updated
- Identical records are ignored

This ensures repeated runs do not create duplicates.

---

## 6. Scheduling Strategy
The scraper runs automatically using APScheduler:

- Runs daily at 02:00 AM (Asia/Karachi)
- Single instance execution enabled
- Missed runs handled with grace time

---

## 7. Site Etiquette
The scraper follows responsible scraping practices:

- Checks robots.txt before scraping
- Uses a custom User-Agent
- Adds delay between requests
- Avoids parallel or aggressive scraping

---

## 8. Design Philosophy
The system is designed to be:

- Modular
- Reliable
- Fault tolerant
- Easy to extend
- Safe for repeated automated execution