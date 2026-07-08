"""
metadata_enrichment.py

Builds the full 33-field metadata JSON (Section 4 of the task brief) for a
single Sindh High Court judgment, by combining:

  1. Deterministic fields  — computed directly from the scraped listing data
     and the citation rules in Section 5 (no LLM involved).
  2. LLM-derived fields    — extracted from the judgment's markdown text by
     a local Ollama model, for anything that requires actually reading the
     judgment (parties, judges, statutes cited, summaries, etc).

Usage:
    from metadata_enrichment import build_full_metadata

    metadata = build_full_metadata(
        case=case,                 # raw dict from scraper._parse_table
        pdf_filename="Sindh High Court - 2026SHC153.pdf",
        markdown_text=full_judgment_text,
        reference_url=case["pdf_url"],
    )
"""

import os
import re
import json
import logging

import ollama

log = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")

COURT_NAME = "Sindh High Court"
COURT_TYPE = "Sindh High Court"
CITATION_JOURNAL = "SHC"

# Same head+tail strategy used in Stage 2 (see DECISIONS.md) to avoid
# blowing the LLM's context window on very long judgments.
HEAD_CHARS = 6000
TAIL_CHARS = 3000

# Citation on the listing looks like: "2026 SHC 87"
CITATION_PATTERN = re.compile(r"^\s*(\d{4})\s+SHC\s+(\d+)\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Section 5 — Case Number & citation policy
# --------------------------------------------------------------------------

def resolve_citation_fields(case: dict) -> dict:
    """
    Implements Section 5.1 / 5.2 exactly:
      - if the listing has a parseable "YYYY SHC NNN" citation, use it for
        Case Number + citation_year/journal/page_number.
      - otherwise, fall back to the court's own case file number, and the
        three citation_* fields are null.
    """
    raw_citation = (case.get("citation") or "").strip()
    match = CITATION_PATTERN.match(raw_citation)

    if match:
        year, page_number = match.groups()
        return {
            "Case Number": raw_citation,
            "citation_year": int(year),
            "citation_journal": CITATION_JOURNAL,
            "citation_page_number": page_number,
        }

    # No usable citation yet — fall back to case file number (Section 5.2).
    fallback_case_no = case.get("case_no") or case.get("code") or None
    return {
        "Case Number": fallback_case_no,
        "citation_year": None,
        "citation_journal": None,
        "citation_page_number": None,
    }


# --------------------------------------------------------------------------
# Deterministic fields (Section 4.2 — anything not requiring the LLM)
# --------------------------------------------------------------------------

def build_deterministic_fields(case: dict, pdf_filename: str, reference_url: str) -> dict:
    file_stem = os.path.splitext(pdf_filename)[0]
    citation_fields = resolve_citation_fields(case)

    return {
        "source_file": pdf_filename,
        "fileName": file_stem,
        "Page count": None,
        "Court Name": COURT_NAME,
        "courtType": COURT_TYPE,
        "Case Title": case.get("topic"),  # best available from listing; LLM may refine
        **citation_fields,
        "case_filing_date": None,
        "trial_court_decision_date": None,
        "appellate_court_decision_date": None,
        "supreme_court_decision_date": None,
        "reference_url": reference_url,
        "content": "",   # filled in by caller from the markdown text
        "source_url": "",  # left empty — populated downstream per brief
    }


# --------------------------------------------------------------------------
# LLM-derived fields
# --------------------------------------------------------------------------

LLM_FIELDS = [
    "Type of Petition or Application",
    "case_category",
    "disposition_type",
    "bench_strength",
    "high_court_decision_date",
    "Hearing Date",
    "Decision/Order Date",
    "petitioner_appellant",
    "respondent",
    "Applicant and Respondents",
    "Advocate Names for each party",
    "Judge Name(s)",
    "FIR Number and Date",
    "Legal Sections Involved",
    "articles_sections_cited",
    "statutes_mentioned",
    "key_legal_issues",
    "head_note",
    "Cited Case Laws",
    "precedents_cited",
    "Short Summary of the Case",
    "legal_keywords",
    "final_decision",
]

_PROMPT_TEMPLATE = """You are a legal-data extraction assistant. Read the Sindh High Court judgment
text below and return ONLY a single JSON object (no prose, no markdown fences) with exactly these
keys:

{field_list}

Rules:
- Dates must be "YYYY-MM-DD" strings, or null if not stated.
- "bench_strength" must be an integer (number of judges), or null.
- Array fields ("articles_sections_cited", "statutes_mentioned", "key_legal_issues",
  "precedents_cited", "legal_keywords") must be JSON arrays of strings. Use [] if none found.
- "FIR Number and Date" must be null unless this is a criminal case.
- "head_note" and "Short Summary of the Case" are SYNTHESIZED fields: write them yourself in your
  own words from the judgment's facts and outcome. Only use null for these two if the text is too
  garbled/short to summarize at all — do not use null just because no pre-written headnote exists
  in the source.
- For every other field, use null only if the fact genuinely is not stated anywhere in the text.
- Do not invent facts that are not in the text.

Judgment text:
---
{judgment_text}
---

Return only the JSON object.
"""


def _truncate_judgment(markdown_text: str) -> str:
    if len(markdown_text) <= HEAD_CHARS + TAIL_CHARS:
        return markdown_text
    return (
        markdown_text[:HEAD_CHARS]
        + "\n\n...[middle omitted]...\n\n"
        + markdown_text[-TAIL_CHARS:]
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


ARRAY_FIELDS = {
    "articles_sections_cited", "statutes_mentioned",
    "key_legal_issues", "precedents_cited", "legal_keywords",
}


def _coerce_to_string(value):
    """Enforce the schema's string/null contract regardless of what shape the LLM returned."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in ("null", "none", "n/a", "na", "unknown"):
            return None
        # LLMs sometimes double-encode: a string that is itself a JSON
        # list/dict (e.g. '["a", "b"]'). Detect and unwrap it recursively
        # instead of keeping the raw JSON syntax as the "string".
        if stripped[0] in "[{":
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, (list, dict)):
                    return _coerce_to_string(parsed)
            except json.JSONDecodeError:
                pass
        return stripped
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if v not in (None, "")]
        return "; ".join(parts) if parts else None
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if v not in (None, "")]
        return "; ".join(parts) if parts else None
    return str(value)


def _coerce_to_list(value):
    """Enforce the schema's array-of-strings contract."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v not in (None, "")]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _coerce_bench_strength(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_llm_fields(markdown_text: str) -> dict:
    """
    Calls the local Ollama model to extract the fields that require reading
    the judgment text. Returns a dict with all LLM_FIELDS keys, defaulting
    to null/[] on any parse failure so the pipeline never crashes on a bad
    LLM response — it just produces a sparser (but valid) metadata record.
    """
    prompt = _PROMPT_TEMPLATE.format(
        field_list=", ".join(f'"{f}"' for f in LLM_FIELDS),
        judgment_text=_truncate_judgment(markdown_text),
    )

    fallback = {f: ([] if f in (
        "articles_sections_cited", "statutes_mentioned",
        "key_legal_issues", "precedents_cited", "legal_keywords"
    ) else None) for f in LLM_FIELDS}

    try:
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = _strip_code_fences(response["message"]["content"])
        parsed = json.loads(raw_text)
    except (KeyError, json.JSONDecodeError, Exception) as exc:
        log.warning("LLM metadata extraction failed (%s) — using nulls.", exc)
        return fallback

    # Merge over the fallback, coercing each value to the type the schema
    # declares (Section 4.2) regardless of what shape the LLM actually
    # returned — this is what turned "" and lists/dicts into schema-correct
    # null/string/array values.
    result = dict(fallback)
    for key in LLM_FIELDS:
        if key not in parsed:
            continue
        value = parsed[key]
        if key in ARRAY_FIELDS:
            result[key] = _coerce_to_list(value)
        elif key == "bench_strength":
            result[key] = _coerce_bench_strength(value)
        else:
            result[key] = _coerce_to_string(value)

    return result


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def build_full_metadata(
    case: dict,
    pdf_filename: str,
    markdown_text: str,
    reference_url: str,
) -> dict:
    """
    Returns the complete 33-field metadata dict, in the exact key order
    required by Section 4 of the brief.
    """
    deterministic = build_deterministic_fields(case, pdf_filename, reference_url)
    llm_fields = extract_llm_fields(markdown_text)

    # "Decision/Order Date" defaults to the same value as
    # high_court_decision_date when the LLM didn't extract it separately
    # (per Section 4.2: "Same as high_court_decision_date in most cases").
    if not llm_fields.get("Decision/Order Date"):
        llm_fields["Decision/Order Date"] = llm_fields.get("high_court_decision_date")

    ordered = {
        "source_file": deterministic["source_file"],
        "fileName": deterministic["fileName"],
        "Page count": deterministic["Page count"],
        "Court Name": deterministic["Court Name"],
        "courtType": deterministic["courtType"],
        "Case Title": deterministic["Case Title"],
        "Case Number": deterministic["Case Number"],
        "Type of Petition or Application": llm_fields["Type of Petition or Application"],
        "case_category": llm_fields["case_category"],
        "disposition_type": llm_fields["disposition_type"],
        "bench_strength": llm_fields["bench_strength"],
        "citation_year": deterministic["citation_year"],
        "citation_journal": deterministic["citation_journal"],
        "citation_page_number": deterministic["citation_page_number"],
        "case_filing_date": deterministic["case_filing_date"],
        "trial_court_decision_date": deterministic["trial_court_decision_date"],
        "appellate_court_decision_date": deterministic["appellate_court_decision_date"],
        "high_court_decision_date": llm_fields["high_court_decision_date"],
        "supreme_court_decision_date": deterministic["supreme_court_decision_date"],
        "Hearing Date": llm_fields["Hearing Date"],
        "Decision/Order Date": llm_fields["Decision/Order Date"],
        "petitioner_appellant": llm_fields["petitioner_appellant"],
        "respondent": llm_fields["respondent"],
        "Applicant and Respondents": llm_fields["Applicant and Respondents"],
        "Advocate Names for each party": llm_fields["Advocate Names for each party"],
        "Judge Name(s)": llm_fields["Judge Name(s)"],
        "FIR Number and Date": llm_fields["FIR Number and Date"],
        "Legal Sections Involved": llm_fields["Legal Sections Involved"],
        "articles_sections_cited": llm_fields["articles_sections_cited"],
        "statutes_mentioned": llm_fields["statutes_mentioned"],
        "key_legal_issues": llm_fields["key_legal_issues"],
        "head_note": llm_fields["head_note"],
        "Cited Case Laws": llm_fields["Cited Case Laws"],
        "precedents_cited": llm_fields["precedents_cited"],
        "Short Summary of the Case": llm_fields["Short Summary of the Case"],
        "legal_keywords": llm_fields["legal_keywords"],
        "final_decision": llm_fields["final_decision"],
        "reference_url": deterministic["reference_url"],
        "content": markdown_text,
        "source_url": deterministic["source_url"],
    }

    return ordered

if __name__ == "__main__":

    import json

    case = {
        "code": "test",
        "citation": "2026 SHC 87",
        "topic": "Test v. State",
        "case_no": "C.P. 123/2025",
    }

    with open("markdown/18510.md", encoding="utf-8") as f:
        md_text = f.read()

    result = build_full_metadata(
        case=case,
        pdf_filename="Sindh High Court - 2026SHC87.pdf",
        markdown_text=md_text,
        reference_url="https://example.com/test.pdf",
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))