"""
query_classifier.py

Rule-based query classifier for Stage 3.

Determines whether a user query belongs to the Sindh High Court case-law
corpus before retrieval is attempted.
"""

import re

CASE_NUMBER_PATTERN = re.compile(r"\d+/\d{4}")

LEGAL_TERMS = {
    "case",
    "court",
    "judge",
    "judgment",
    "order",
    "appeal",
    "petition",
    "plaintiff",
    "defendant",
    "respondent",
    "appellant",
    "cargo",
    "vessel",
    "ship",
    "nazir",
    "admiralty",
    "bail",
    "sentence",
    "prison",
    "security",
    "decree",
    "cheque",
    "claim",
    "release",
    "suit",
}

WRONG_JURISDICTIONS = {
    "lahore high court",
    "islamabad high court",
    "peshawar high court",
    "balochistan high court",
    "california",
    "supreme court of india",
}


def classify_query(query: str) -> str:
    """
    Returns:
        "relevant"
        "irrelevant"
    """

    q = query.lower()

    # exact case number always belongs to corpus
    if CASE_NUMBER_PATTERN.search(q):
        return "relevant"

    # explicitly asking about another court
    for item in WRONG_JURISDICTIONS:
        if item in q:
            return "irrelevant"

    # count legal keywords
    score = sum(term in q for term in LEGAL_TERMS)

    if score >= 1:
        return "relevant"

    return "irrelevant"