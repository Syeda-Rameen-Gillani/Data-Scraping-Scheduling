"""
external_api.py

Client for the external Judgment API (Section 10 of the brief), which sits
in front of the staging MongoDB. Every judgment uploaded to S3 must also be
POSTed (new) or PUT-updated (citation change) to this API.

Usage:
    from external_api import upsert_judgment

    result = upsert_judgment(metadata, known_to_api=False)
    if result.success:
        ...
"""

import os
import logging
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

BASE_URL = "https://sb.pakistanlawbot.com/api"
CREATE_URL = f"{BASE_URL}/external/judgment"
UPDATE_URL = f"{BASE_URL}/external/judgment/by-filename"

API_KEY = os.getenv("EXTERNAL_JUDGMENT_API_KEY")
REQUEST_TIMEOUT = 30


class ApiAuthError(Exception):
    """Raised on 401 — bad or missing API key. Callers should halt the run."""


@dataclass
class ApiResult:
    success: bool
    status_code: int | None
    judgment_id: str | None = None
    action: str = ""   # "created", "updated", "skipped", "failed"
    detail: str = ""


def _headers() -> dict:
    if not API_KEY:
        raise ApiAuthError("EXTERNAL_JUDGMENT_API_KEY is not set in the environment.")
    return {
        "x-api-key": API_KEY,
        "Content-Type": "application/json",
    }


def create_judgment(metadata: dict) -> ApiResult:
    """
    POST a new judgment. Section 10.3.
    """
    try:
        resp = requests.post(
            CREATE_URL,
            json=metadata,
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        log.error("POST failed (network error): %s", exc)
        return ApiResult(success=False, status_code=None, action="failed", detail=str(exc))

    if resp.status_code == 201:
        body = resp.json()
        return ApiResult(
            success=True,
            status_code=201,
            judgment_id=body.get("judgmentId"),
            action="created",
        )

    if resp.status_code == 409:
        return ApiResult(success=False, status_code=409, action="duplicate", detail=resp.text)

    if resp.status_code == 401:
        raise ApiAuthError("API rejected the credential (401). Halting run.")

    if resp.status_code == 400:
        log.error("POST validation failed (400): %s", resp.text)
        return ApiResult(success=False, status_code=400, action="failed", detail=resp.text)

    log.error("POST unexpected status %s: %s", resp.status_code, resp.text)
    return ApiResult(success=False, status_code=resp.status_code, action="failed", detail=resp.text)


def update_judgment_by_filename(metadata: dict) -> ApiResult:
    """
    PUT an updated judgment, looked up by fileName. Section 10.4.
    """
    if not metadata.get("fileName"):
        raise ValueError("metadata must include 'fileName' for the update endpoint.")

    try:
        resp = requests.put(
            UPDATE_URL,
            json=metadata,
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        log.error("PUT failed (network error): %s", exc)
        return ApiResult(success=False, status_code=None, action="failed", detail=str(exc))

    if resp.status_code == 200:
        return ApiResult(success=True, status_code=200, action="updated")

    if resp.status_code == 404:
        return ApiResult(success=False, status_code=404, action="not_found", detail=resp.text)

    if resp.status_code == 401:
        raise ApiAuthError("API rejected the credential (401). Halting run.")

    if resp.status_code == 400:
        log.error("PUT validation failed (400): %s", resp.text)
        return ApiResult(success=False, status_code=400, action="failed", detail=resp.text)

    log.error("PUT unexpected status %s: %s", resp.status_code, resp.text)
    return ApiResult(success=False, status_code=resp.status_code, action="failed", detail=resp.text)


def upsert_judgment(metadata: dict, known_to_api: bool) -> ApiResult:
    """
    Orchestrates the POST/PUT decision per Section 10.5 and the edge cases
    in Section 11.4.

    Args:
        metadata: full metadata dict (Section 4 schema), must include fileName.
        known_to_api: True if this judgment was already in processed_ids.json
                      on a previous run (i.e. this is a citation-update call,
                      not a brand new judgment).

    Returns:
        ApiResult with action in {"created", "updated", "failed"}.
    """
    if known_to_api:
        result = update_judgment_by_filename(metadata)
        if result.success:
            return result
        if result.status_code == 404:
            # Section 11.4: never made it to MongoDB on a previous run —
            # fall back to creating it now.
            log.info(
                "PUT returned 404 for fileName=%s — falling back to POST.",
                metadata.get("fileName"),
            )
            return create_judgment(metadata)
        return result

    # Not known yet — attempt create.
    result = create_judgment(metadata)
    if result.success:
        return result
    if result.status_code == 409:
        # Section 10.3: duplicate Case Number + courtType — switch to update.
        log.info(
            "POST returned 409 for fileName=%s — falling back to PUT.",
            metadata.get("fileName"),
        )
        return update_judgment_by_filename(metadata)
    return result