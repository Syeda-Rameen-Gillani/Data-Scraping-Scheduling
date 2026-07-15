import os
import re
import time
import json
import logging

import ollama
from google import genai
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
# gemini-2.0-flash's free tier has been narrowing throughout 2026 in favor of
# the 2.5 line; 2.5-flash is the current confirmed free-eligible default.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Retry policy for transient LLM failures (network blips, 503s, momentary
# rate limiting). Exponential backoff: 10s, 20s, 40s, 80s, 160s.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))
LLM_RETRY_BASE_SECONDS = int(os.getenv("LLM_RETRY_BASE_SECONDS", "10"))

gemini_client = None

if LLM_PROVIDER == "gemini":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in the .env file.")
    gemini_client = genai.Client(api_key=api_key)

COURT_NAME = "Sindh High Court"
COURT_TYPE = "Sindh High Court"
CITATION_JOURNAL = "SHC"

# Same head+tail strategy used in Stage 2 (see DECISIONS.md) to avoid
# blowing the LLM's context window on very long judgments.
HEAD_CHARS = 6000
TAIL_CHARS = 3000

# A judgment's legal reasoning (where precedents/statutes are actually
# cited) is often in the middle and gets cut by the head+tail truncation
# above. Rather than inflating HEAD/TAIL for every document, we scan the
# FULL text for citation-shaped substrings and splice a short "recovered
# citations" block into the prompt so the model still sees them even when
# they fall in the omitted middle.
MAX_RECOVERED_CITATION_CHARS = 1500

# Citation on the listing looks like: "2026 SHC 87"
CITATION_PATTERN = re.compile(r"^\s*(\d{4})\s+SHC\s+(\d+)\s*$", re.IGNORECASE)

# Rough patterns for in-text law-report citations, in either order:
#   "1989 CLC 2168" / "PLD 1993 SC 88" / "2011 CLD 1329"
_CITATION_TOKEN = re.compile(
    r"""
    (?:\b(19|20)\d{2}\s+[A-Z]{2,6}\s+\d+\b)        # YEAR REPORTER PAGE
    |
    (?:\b[A-Z]{2,6}\s+(19|20)\d{2}\s+[A-Z]{0,3}\s*\d+\b)  # REPORTER YEAR (SC) PAGE
    """,
    re.VERBOSE,
)

# "X v. Y" / "X v Y" case-name patterns, used to grab the surrounding
# sentence so the citation has its case name attached.
_CASE_NAME_HINT = re.compile(r"[A-Z][\w.&'\-]*(?:\s+[\w.&'\-]+){0,6}\s+v\.?\s+[A-Z][\w.&'\-\"“”]+")


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
    "Case Title",
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

ARRAY_FIELDS = {
    "articles_sections_cited", "statutes_mentioned",
    "key_legal_issues", "precedents_cited", "legal_keywords",
}

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
- For every other field:

- Extract the value if it is explicitly stated.
- If the value can be determined directly from the judgment heading, party caption, advocate appearances, order sheet, or procedural history without guessing, extract it.
- Do not infer or invent names or facts that are not supported by the judgment text.
- Use null only when the value genuinely cannot be determined from the judgment.

Return actual JSON arrays.

Correct:
[]

["Section 302 PPC"]

Incorrect:

"[]"

"['Section 302 PPC']"

"null"

"N/A"

If the judgment is only an Order Sheet, procedural order, or short order:

- Still extract every field that can reasonably be identified.
- Do not leave fields null merely because the judgment is short.
If the judgment is only an Order Sheet, procedural order, or short order:

- Extract every field that is actually available.
- If a party, judge, or case title is not present, return null.
- Do not substitute generic labels such as "Appellant", "Respondent", or "JUDGE" for missing names.

For "Judge Name(s)":
- Return the full judge name exactly as written.
- If only initials or a surname appear, return that partial name.
- Do not invent missing parts of a name.
- Return the judge's actual name.
- Do NOT return words like:
    "JUDGE"
    "J U D G E"
    "HON'BLE JUDGE"
    "COURT"
- If no actual name appears, return null.

For "petitioner_appellant":

- Return the actual name of the petitioner/appellant.
- Do NOT return generic words like:
  "Appellant"
  "Petitioner"
  "Applicant"
  "Plaintiff"
  "Respondent"
- If the party's name is not stated, return null.

For "respondent":

- Return the actual name of the respondent.
- Do NOT return generic words like:
  "Respondent"
  "Defendant"
  "Opposite Party"
- If the respondent's name is not stated, return null.

For "Case Title":

- "Case Title" means the names of the opposing parties (for example,
  "ABC Ltd. vs XYZ Ltd.").

- It MUST NOT be the case number.

- It MUST NOT contain values like:
  "Civil Appeal No. 25/2020"
  "Criminal Bail No. 1254/2017"
  "IInd Appeal No. 68/2013"

- If the title is not explicitly printed, construct it from the petitioner/appellant
  and respondent names.

- If only one party name can be identified, return that party name.

- Return null only if neither party can be identified.

If the respondent or petitioner is not explicitly labelled but can be identified from the case heading or advocate appearances, extract it.

- Do not invent facts that are not in the text.
- The "Judgment text" section below may have its middle omitted for length. A separate
  "Recovered citation snippets" section (if present) contains short excerpts pulled from that
  omitted middle specifically because they look like case citations or statute references — use
  them for "Cited Case Laws", "precedents_cited", "articles_sections_cited", and
  "statutes_mentioned" even though they aren't part of the continuous text.

  Important:

- Do not return empty arrays or null unless the information genuinely cannot be determined from the judgment.
- If a legal issue, statute, article, precedent, or keyword is mentioned anywhere in the judgment, extract it.
- Return clean arrays of strings, not strings containing JSON.
- Do not return values like "[]", "null", "N/A", or "Unknown" as strings.
- Only return valid JSON.
Do not infer names that are not explicitly written.

If the judgment only refers to a party as
"Appellant",
"Respondent",
"Petitioner",
"Applicant",
"Plaintiff",
or "Defendant",

and the actual person's or organization's name is not written,
return null.

Judgment text:
---
{judgment_text}
---
{recovered_citations_block}
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


def _recover_middle_citations(full_text: str, truncated_text: str) -> str:
    """
    If the middle of the judgment was cut, scan the OMITTED portion for
    citation-shaped substrings ("1989 CLC 2168", "PLD 1993 SC 88", etc.)
    and case-name hints ("X v. Y"), and return a short block of the
    sentences containing them so the LLM doesn't lose precedents that
    happen to sit outside the head/tail window.
    """
    if truncated_text == full_text:
        return ""  # nothing was cut

    head = full_text[:HEAD_CHARS]
    tail = full_text[-TAIL_CHARS:]
    middle = full_text[HEAD_CHARS: len(full_text) - TAIL_CHARS]
    if not middle.strip():
        return ""

    # Collect match spans from both patterns first, then merge any that
    # overlap or sit close together, so a citation matched by both
    # patterns (or two citations near each other) produces ONE snippet
    # instead of duplicated/overlapping context windows.
    CONTEXT_CHARS = 150
    spans = []
    for pattern in (_CITATION_TOKEN, _CASE_NAME_HINT):
        for hit in pattern.finditer(middle):
            spans.append((hit.start(), hit.end()))

    if not spans:
        return ""

    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start - CONTEXT_CHARS <= merged[-1][1] + CONTEXT_CHARS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    block = ""
    for start, end in merged:
        win_start = max(0, start - CONTEXT_CHARS)
        win_end = min(len(middle), end + CONTEXT_CHARS)
        snippet = re.sub(r"\s+", " ", middle[win_start:win_end].strip())
        if not snippet:
            continue
        addition = f"- {snippet}\n"
        if len(block) + len(addition) > MAX_RECOVERED_CITATION_CHARS:
            break
        block += addition

    if not block:
        return ""

    return "\nRecovered citation snippets (from the omitted middle section):\n" + block


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


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
                parsed_inner = json.loads(stripped)
                if isinstance(parsed_inner, (list, dict)):
                    return _coerce_to_string(parsed_inner)
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


class MetadataExtractionError(Exception):
    """
    Raised when metadata extraction genuinely fails — either the LLM call
    never succeeded after retries, or it returned something that isn't
    parseable JSON. Callers (the ingestion pipeline) are expected to catch
    this, log the document to a failed-jobs queue, and move on to the next
    PDF rather than publishing a record with mostly-null fields.
    """

    def __init__(self, pdf_filename: str, reason: str):
        self.pdf_filename = pdf_filename
        self.reason = reason
        super().__init__(f"{pdf_filename}: {reason}")


# Errors worth retrying: momentary unavailability, timeouts, or a rate
# limit that has real (non-zero) headroom which just needs a short wait.
_TRANSIENT_ERROR_MARKERS = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timeout", "Timeout")

# A quota violation that reports "limit: 0" is NOT transient — it means
# this project/model combination has zero free-tier allocation at all
# (e.g. billing not linked, or the model was dropped from the free tier).
# Retrying with backoff just burns 5+ minutes per document for a wall that
# backoff can't get through. Fail fast instead with a message that points
# at the actual fix.
_HARD_ZERO_QUOTA_PATTERN = re.compile(r"limit[\"']?\s*:\s*[\"']?0\b")


def _is_retryable(error_message: str) -> bool:
    if _HARD_ZERO_QUOTA_PATTERN.search(error_message):
        return False
    return any(marker in error_message for marker in _TRANSIENT_ERROR_MARKERS)


def _call_llm(prompt: str) -> str:
    """
    Provider-agnostic call. Returns the raw text response.
    Retries transient failures with exponential backoff (10s, 20s, 40s,
    80s, 160s by default). Raises immediately — no retry — on a hard
    zero-quota error, since backoff cannot fix a config problem.
    """
    last_error = None

    for attempt in range(LLM_MAX_RETRIES):
        try:
            if LLM_PROVIDER == "gemini":
                response = gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
                return response.text or ""

            # Default: local Ollama. format="json" asks the model to
            # constrain its output to valid JSON where the model supports it.
            response = ollama.chat(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0},
            )
            return response["message"]["content"] or ""

        except Exception as exc:
            last_error = exc
            message = str(exc)

            if _HARD_ZERO_QUOTA_PATTERN.search(message):
                raise RuntimeError(
                    f"{LLM_PROVIDER} reports zero quota for this project/model "
                    f"(not a transient rate limit) — check billing is linked "
                    f"and that the model is still free-tier eligible. "
                    f"Original error: {message}"
                ) from exc

            if not _is_retryable(message) or attempt == LLM_MAX_RETRIES - 1:
                raise

            wait = LLM_RETRY_BASE_SECONDS * (2 ** attempt)
            log.warning(
                "%s call failed (attempt %d/%d), retrying in %ds: %s",
                LLM_PROVIDER, attempt + 1, LLM_MAX_RETRIES, wait, message,
            )
            time.sleep(wait)

    raise RuntimeError(f"{LLM_PROVIDER} failed after {LLM_MAX_RETRIES} retries") from last_error


def extract_llm_fields(markdown_text: str, pdf_filename: str = "") -> dict:
    """
    Calls the configured LLM provider to extract the fields that require
    reading the judgment text. Returns a fully-typed dict of all
    LLM_FIELDS keys on success.

    Raises MetadataExtractionError on failure (after retries are
    exhausted, or on unparseable output) rather than silently returning
    null/[] fields — publishing a mostly-empty metadata record into S3/
    Weaviate is worse than not publishing at all. The caller is expected
    to catch this, record the document in a failed-jobs queue, and
    continue with the rest of the batch.
    """
    truncated_text = _truncate_judgment(markdown_text)
    recovered_block = _recover_middle_citations(markdown_text, truncated_text)

    prompt = _PROMPT_TEMPLATE.format(
        field_list=", ".join(f'"{f}"' for f in LLM_FIELDS),
        judgment_text=truncated_text,
        recovered_citations_block=recovered_block,
    )

    try:
        raw_output = _call_llm(prompt)
    except Exception as exc:
        raise MetadataExtractionError(pdf_filename or "<unknown file>", str(exc)) from exc

    cleaned = _strip_code_fences(raw_output)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise MetadataExtractionError(
            pdf_filename or "<unknown file>",
            f"LLM returned unparseable JSON: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise MetadataExtractionError(
            pdf_filename or "<unknown file>",
            f"LLM returned valid JSON but not an object (got {type(parsed).__name__})",
        )

    # Coerce each value to the type the schema declares (Section 4.2)
    # regardless of what shape the LLM actually returned — this turns ""
    # and lists/dicts into schema-correct null/string/array values.
    fallback = {f: ([] if f in ARRAY_FIELDS else None) for f in LLM_FIELDS}
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

    Raises MetadataExtractionError if the LLM extraction step fails after
    retries (or returns unparseable output). This is intentional: the
    ingestion pipeline should catch it, log the document to a failed-jobs
    queue, and move on — not upload a record with the LLM-derived fields
    silently nulled out.
    """
    deterministic = build_deterministic_fields(case, pdf_filename, reference_url)
    llm_fields = extract_llm_fields(markdown_text, pdf_filename=pdf_filename)

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
        "Case Title": (
            llm_fields["Case Title"]
            or deterministic["Case Title"]
        ),
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

    with open("markdown/Sindh High Court - MjAwNjIyY2Ztcy1kYzgz.md", encoding="utf-8") as f:
        md_text = f.read()

    print(f"Using {LLM_PROVIDER}...")
    if LLM_PROVIDER == "gemini":
        print(f"Model: {GEMINI_MODEL}")
    else:
        print(f"Model: {LLM_MODEL}")

    try:
        result = build_full_metadata(
            case=case,
            pdf_filename="Sindh High Court - 2026SHC87.pdf",
            markdown_text=md_text,
            reference_url="https://example.com/test.pdf",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except MetadataExtractionError as exc:
        # This is what the ingestion script's failed-jobs queue should
        # catch — see build_full_metadata's docstring.
        print(f"Metadata extraction FAILED for {exc.pdf_filename}: {exc.reason}")