"""
test_scraper.py
===============
Automated tests for scraper.py.

Run with:
    pytest test_scraper.py -v

No network access is required — every external call is mocked.
"""

import importlib
import sys
import types
import pytest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# We need to import scraper, but it calls os.makedirs and sets up a file-
# based logger at import time.  Patch those side-effects before the import.
# ---------------------------------------------------------------------------
import builtins
import os

# Prevent the "logs/" directory from being created during tests
os.makedirs = lambda *a, **kw: None  # type: ignore[assignment]

import scraper  # noqa: E402  (import after patching)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_html(rows: list[dict]) -> str:
    """
    Build a minimal HTML fragment that _parse_table() can understand.

    Each dict in *rows* may contain: code, s_no, citation, topic, case_no, href.
    """
    tr_rows = ""
    for r in rows:
        href   = r.get("href", "")
        a_open = f'<a href="{href}">' if href else ""
        a_close = "</a>" if href else ""
        tr_rows += (
            f"<tr>"
            f"<td>{a_open}{r.get('code','')}{a_close}</td>"
            f"<td>{r.get('s_no','')}</td>"
            f"<td>{r.get('citation','')}</td>"
            f"<td>{r.get('topic','')}</td>"
            f"<td>{r.get('case_no','')}</td>"
            f"</tr>"
        )
    return f'<table id="tblExport"><tr><th>H</th></tr>{tr_rows}</table>'


# ===========================================================================
# 1.  _parse_table — the pure-HTML-parsing function
# ===========================================================================

class TestParseTable:

    def test_empty_string_returns_empty_list(self):
        assert scraper._parse_table("") == []

    def test_html_without_tblExport_keyword_returns_empty_list(self):
        html = "<table id='other'><tr><td>x</td></tr></table>"
        assert scraper._parse_table(html) == []

    def test_html_with_tblExport_keyword_but_no_table_returns_empty_list(self):
        # The word "tblExport" appears in text, but not as a table id
        html = "tblExport mentioned here but no actual table"
        assert scraper._parse_table(html) == []

    def test_header_row_is_skipped(self):
        html = '<table id="tblExport"><tr><th>H1</th><th>H2</th></tr></table>'
        assert scraper._parse_table(html) == []

    def test_row_with_fewer_than_5_cols_is_skipped(self):
        html = '<table id="tblExport"><tr><th>H</th></tr><tr><td>a</td><td>b</td></tr></table>'
        assert scraper._parse_table(html) == []

    def test_single_valid_row_all_fields_present(self):
        html = _make_html([{
            "code": "C001", "s_no": "1", "citation": "2023 CLD 100",
            "topic": "Contract", "case_no": "HCA 1/2023",
            "href": "/caselaw/detail/C001",
        }])
        records = scraper._parse_table(html)
        assert len(records) == 1
        rec = records[0]
        assert rec["code"]      == "C001"
        assert rec["s_no"]      == "1"
        assert rec["citation"]  == "2023 CLD 100"
        assert rec["topic"]     == "Contract"
        assert rec["case_no"]   == "HCA 1/2023"
        assert rec["detail_url"] == "https://caselaw.shc.gov.pk/caselaw/detail/C001"

    def test_detail_url_is_absolute_when_href_is_relative(self):
        html = _make_html([{
            "code": "C002", "s_no": "2", "citation": "", "topic": "", "case_no": "",
            "href": "/some/relative/path",
        }])
        rec = scraper._parse_table(html)[0]
        assert rec["detail_url"].startswith("https://caselaw.shc.gov.pk")

    def test_detail_url_is_none_when_no_link(self):
        html = _make_html([{
            "code": "C003", "s_no": "3", "citation": "", "topic": "", "case_no": "",
        }])
        rec = scraper._parse_table(html)[0]
        assert rec["detail_url"] is None

    def test_empty_text_fields_become_none(self):
        html = _make_html([{
            "code": "", "s_no": "", "citation": "", "topic": "", "case_no": "",
        }])
        rec = scraper._parse_table(html)[0]
        assert rec["code"]     is None
        assert rec["citation"] is None
        assert rec["topic"]    is None
        assert rec["case_no"]  is None

    def test_whitespace_is_stripped_from_all_fields(self):
        html = _make_html([{
            "code": "  C004  ", "s_no": " 4 ", "citation": " 2024 CLD 5 ",
            "topic": " Tax ", "case_no": " HCA 2/2024 ",
        }])
        rec = scraper._parse_table(html)[0]
        assert rec["code"]     == "C004"
        assert rec["s_no"]     == "4"
        assert rec["citation"] == "2024 CLD 5"
        assert rec["topic"]    == "Tax"
        assert rec["case_no"]  == "HCA 2/2024"

    def test_multiple_rows_all_returned(self):
        rows = [
            {"code": f"C{i:03d}", "s_no": str(i), "citation": f"CIT {i}",
             "topic": "T", "case_no": f"HCA {i}/2023"}
            for i in range(1, 6)
        ]
        records = scraper._parse_table(_make_html(rows))
        assert len(records) == 5
        assert [r["code"] for r in records] == ["C001","C002","C003","C004","C005"]

    def test_all_required_keys_always_present(self):
        html = _make_html([{"code": "X", "s_no": "1", "citation": "C",
                            "topic": "T", "case_no": "N"}])
        rec = scraper._parse_table(html)[0]
        for key in ("code", "s_no", "citation", "topic", "case_no", "detail_url"):
            assert key in rec, f"Key '{key}' missing from record"


# ===========================================================================
# 2.  _base_payload — default values and overrides
# ===========================================================================

class TestBasePayload:

    REQUIRED_KEYS = {
        "STD_JUDGES", "ALL_JUDGES_M_SELECT", "ALL_ADVOCATES_M_SELECT",
        "ALL_TOPICS_M_SELECT", "STD_COURTS", "CASENO", "CASEYEAR",
        "STD_CASETYPES", "STD_BENCHTYPES", "STD_DOCUMENTTYPES",
        "AFR_TF", "PARTYSIDE1_NAMES", "DATE_ORDER_JUDGMENT",
        "DATE_ORDER_JUDGMENT2", "CASEGROUP", "opt",
    }

    def test_all_required_keys_present_by_default(self):
        payload = scraper._base_payload()
        assert self.REQUIRED_KEYS.issubset(payload.keys())

    def test_default_opt_is_search_judgement(self):
        assert scraper._base_payload()["opt"] == "search_judgement"

    def test_override_replaces_default(self):
        payload = scraper._base_payload(CASENO="123", CASEYEAR="2023")
        assert payload["CASENO"]   == "123"
        assert payload["CASEYEAR"] == "2023"

    def test_extra_key_is_added(self):
        payload = scraper._base_payload(page="2")
        assert payload["page"] == "2"

    def test_original_defaults_not_mutated_between_calls(self):
        scraper._base_payload(CASENO="mutate_me")
        assert scraper._base_payload()["CASENO"] == ""


# ===========================================================================
# 3.  _robots_allow — robots.txt caching and permission logic
# ===========================================================================

class TestRobotsAllow:

    def setup_method(self):
        # Reset the module-level cache before each test
        scraper._robot_parser = None

    def _patch_parser(self, can_fetch_return: bool):
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = can_fetch_return
        return patch("scraper.RobotFileParser", return_value=mock_rp), mock_rp

    def test_returns_true_when_robots_allows(self):
        patcher, mock_rp = self._patch_parser(True)
        with patcher:
            assert scraper._robots_allow("https://example.com/page") is True

    def test_returns_false_when_robots_disallows(self):
        patcher, mock_rp = self._patch_parser(False)
        with patcher:
            assert scraper._robots_allow("https://example.com/page") is False

    def test_robots_txt_fetched_only_once_across_multiple_calls(self):
        patcher, mock_rp = self._patch_parser(True)
        with patcher:
            scraper._robots_allow("https://example.com/a")
            scraper._robots_allow("https://example.com/b")
            scraper._robots_allow("https://example.com/c")
        # RobotFileParser() constructor called once; read() called once
        assert mock_rp.read.call_count == 1

    def test_proceeds_when_robots_txt_unreachable(self):
        mock_rp = MagicMock()
        mock_rp.read.side_effect = Exception("connection refused")
        mock_rp.can_fetch.return_value = True
        with patch("scraper.RobotFileParser", return_value=mock_rp):
            # Should NOT raise; should return True (cautious proceed)
            result = scraper._robots_allow("https://example.com/page")
        assert result is True


# ===========================================================================
# 4.  _post_with_retry — network retries, back-off, and JSON parsing
# ===========================================================================

class TestPostWithRetry:

    def setup_method(self):
        # Speed tests up: eliminate real sleep() calls
        self.sleep_patcher = patch("scraper.time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def teardown_method(self):
        self.sleep_patcher.stop()

    def _mock_response(self, json_data=None, status_code=200, raise_for_status=None):
        resp = MagicMock()
        resp.status_code = status_code
        if raise_for_status:
            resp.raise_for_status.side_effect = raise_for_status
        else:
            resp.raise_for_status.return_value = None
        resp.json.return_value = json_data or {"msg": ""}
        return resp

    def test_returns_json_on_first_success(self):
        expected = {"msg": "<table id='tblExport'></table>"}
        with patch("scraper.requests.post", return_value=self._mock_response(expected)):
            result = scraper._post_with_retry({"key": "value"})
        assert result == expected

    def test_returns_none_after_all_retries_exhausted(self):
        import requests as req
        with patch("scraper.requests.post", side_effect=req.exceptions.Timeout):
            result = scraper._post_with_retry({"key": "value"})
        assert result is None

    def test_retries_exactly_retry_limit_times(self):
        import requests as req
        with patch("scraper.requests.post", side_effect=req.exceptions.Timeout) as mock_post:
            scraper._post_with_retry({})
        assert mock_post.call_count == scraper.RETRY_LIMIT

    def test_sleeps_between_retries_but_not_after_last(self):
        import requests as req
        with patch("scraper.requests.post", side_effect=req.exceptions.Timeout):
            scraper._post_with_retry({})
        # Should sleep RETRY_LIMIT-1 times (not after the final attempt)
        assert self.mock_sleep.call_count == scraper.RETRY_LIMIT - 1

    def test_succeeds_on_second_attempt_after_one_failure(self):
        import requests as req
        good_resp = self._mock_response({"msg": "ok"})
        with patch(
            "scraper.requests.post",
            side_effect=[req.exceptions.Timeout, good_resp],
        ):
            result = scraper._post_with_retry({})
        assert result == {"msg": "ok"}

    def test_returns_none_on_http_error(self):
        import requests as req
        bad_resp = self._mock_response(
            raise_for_status=req.exceptions.HTTPError("500")
        )
        with patch("scraper.requests.post", return_value=bad_resp):
            result = scraper._post_with_retry({})
        assert result is None

    def test_returns_none_on_json_decode_error(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("No JSON")
        with patch("scraper.requests.post", return_value=resp):
            result = scraper._post_with_retry({})
        assert result is None

    def test_back_off_waits_increase_with_each_attempt(self):
        import requests as req
        with patch("scraper.requests.post", side_effect=req.exceptions.Timeout):
            scraper._post_with_retry({})
        wait_times = [c.args[0] for c in self.mock_sleep.call_args_list]
        # Each wait should be larger than the previous one
        for i in range(1, len(wait_times)):
            assert wait_times[i] > wait_times[i - 1], (
                f"Back-off did not increase: {wait_times}"
            )


# ===========================================================================
# 5.  scrape_cases — the main orchestration function (integration-level)
# ===========================================================================

class TestScrapeCases:

    def setup_method(self):
        scraper._robot_parser = None
        self.sleep_patcher = patch("scraper.time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def teardown_method(self):
        self.sleep_patcher.stop()

    def _allow_robots(self):
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True
        return patch("scraper.RobotFileParser", return_value=mock_rp)

    def _page_response(self, rows: list[dict]) -> dict:
        return {"msg": _make_html(rows)}

    def _empty_response(self) -> dict:
        return {"msg": ""}

    # -- robots.txt blocks all access ----------------------------------------

    def test_returns_empty_list_when_robots_blocks(self):
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = False
        with patch("scraper.RobotFileParser", return_value=mock_rp):
            result = scraper.scrape_cases()
        assert result == []

    # -- single page scenarios -----------------------------------------------

    def test_single_page_of_results_returned_correctly(self):
        rows = [{"code": "A1", "s_no": "1", "citation": "C1",
                 "topic": "T1", "case_no": "N1"}]
        with self._allow_robots():
            with patch("scraper._post_with_retry", return_value=self._page_response(rows)):
                result = scraper.scrape_cases()
        assert len(result) == 1
        assert result[0]["code"] == "A1"

    def test_stops_when_first_page_is_empty(self):
        with self._allow_robots():
            with patch("scraper._post_with_retry", return_value=self._empty_response()):
                result = scraper.scrape_cases()
        assert result == []

    def test_stops_when_post_returns_none(self):
        with self._allow_robots():
            with patch("scraper._post_with_retry", return_value=None):
                result = scraper.scrape_cases()
        assert result == []

    # -- multi-page scenarios ------------------------------------------------

    def test_collects_records_across_multiple_pages(self):
        page1 = [{"code": "P1R1", "s_no": "1", "citation": "", "topic": "", "case_no": ""}]
        page2 = [{"code": "P2R1", "s_no": "2", "citation": "", "topic": "", "case_no": ""}]

        responses = [
            self._page_response(page1),
            self._page_response(page2),
            self._empty_response(),   # signals end of data
        ]
        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=responses):
                result = scraper.scrape_cases()
        assert len(result) == 2
        codes = {r["code"] for r in result}
        assert codes == {"P1R1", "P2R1"}

    def test_deduplication_removes_repeated_code_across_pages(self):
        row = {"code": "DUP", "s_no": "1", "citation": "", "topic": "", "case_no": ""}
        responses = [
            self._page_response([row]),  # page 1 — first time we see DUP
            self._page_response([row]),  # page 2 — same code again → skip
            self._empty_response(),
        ]
        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=responses):
                result = scraper.scrape_cases()
        # DUP should appear exactly once
        assert len(result) == 1

    def test_stops_when_all_records_on_page_are_duplicates(self):
        """If every row on a page is already seen, new_this_page==0 → loop ends."""
        row = {"code": "DUP2", "s_no": "1", "citation": "", "topic": "", "case_no": ""}
        # Two pages with identical content; third call should never be made
        responses = [
            self._page_response([row]),
            self._page_response([row]),  # all dups → loop should stop here
        ]
        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=responses) as mock_post:
                result = scraper.scrape_cases()
        assert mock_post.call_count == 2
        assert len(result) == 1

    def test_max_pages_cap_is_respected(self):
        row = lambda i: {"code": f"R{i}", "s_no": str(i),
                         "citation": "", "topic": "", "case_no": ""}
        # Provide 10 pages of data; cap at 3
        responses = [self._page_response([row(i)]) for i in range(10)]
        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=responses) as mock_post:
                result = scraper.scrape_cases(max_pages=3)
        assert mock_post.call_count == 3
        assert len(result) == 3

    # -- page number is sent correctly ---------------------------------------

    def test_page_number_increments_in_payload(self):
        row = lambda i: {"code": f"R{i}", "s_no": str(i),
                         "citation": "", "topic": "", "case_no": ""}
        responses = [
            self._page_response([row(1)]),
            self._page_response([row(2)]),
            self._empty_response(),
        ]
        captured_payloads = []

        def capture(payload):
            captured_payloads.append(dict(payload))
            return responses.pop(0)

        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=capture):
                scraper.scrape_cases(page_param="page", start_page=1)

        # First request → page=1, second → page=2
        assert captured_payloads[0]["page"] == "1"
        assert captured_payloads[1]["page"] == "2"

    # -- throttle sleep is called between pages ------------------------------

    def test_sleep_is_called_between_pages(self):
        row = lambda i: {"code": f"R{i}", "s_no": str(i),
                         "citation": "", "topic": "", "case_no": ""}
        responses = [
            self._page_response([row(1)]),
            self._page_response([row(2)]),
            self._empty_response(),
        ]
        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=responses):
                scraper.scrape_cases()
        # The loop sleeps at the bottom of every iteration that will continue,
        # i.e. after page 1 (before page 2) and after page 2 (before the empty
        # page 3 terminates the loop).  That is 2 sleeps total.
        assert self.mock_sleep.call_count == 2
        # Every sleep call should use the configured THROTTLE constant
        for c in self.mock_sleep.call_args_list:
            assert c.args[0] == scraper.THROTTLE

    # -- filter parameters forwarded to payload ------------------------------

    def test_caseno_and_caseyear_forwarded_to_payload(self):
        captured = []

        def capture(payload):
            captured.append(dict(payload))
            return self._empty_response()

        with self._allow_robots():
            with patch("scraper._post_with_retry", side_effect=capture):
                scraper.scrape_cases(caseno="42", caseyear="2024")

        assert captured[0]["CASENO"]   == "42"
        assert captured[0]["CASEYEAR"] == "2024"