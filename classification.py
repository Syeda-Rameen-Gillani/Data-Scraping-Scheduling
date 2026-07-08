"""
classification.py

Query classifier (Stage 3, Task 3). Labels an incoming query as one of:

  - "relevant"   -- plausibly answerable from this corpus (Sindh High Court
                    case law: admiralty/cargo disputes, civil suits, criminal
                    bail matters, compromise decrees, etc.)
  - "other"      -- a genuine legal question, but outside this corpus's scope
                    (wrong court/jurisdiction, e.g. Lahore High Court, Indian
                    or US law, or generic legal concepts not tied to a
                    retrievable Sindh High Court judgment)
  - "irrelevant" -- no legal content at all (recipes, tech support, general
                    trivia)

Definition of "irrelevant" for this corpus: anything that isn't a Sindh High
Court case-law question. "other" is kept distinct from "irrelevant" so the
system can give a more specific decline message for off-corpus legal
questions than for pure off-topic chatter, per Task 3's "route appropriately"
requirement -- even though both collapse to the same "don't attempt a full
RAG answer" decision.

Known failure mode (see DECISIONS.md): borderline questions that mention
legal-sounding terms but are actually generic (e.g. "what is a contract?")
can be misclassified as "relevant" by a 3B model, since it pattern-matches on
surface vocabulary rather than truly checking corpus scope. This is a real,
acknowledged limitation, not silently ignored.
"""

import os
import re
import json
import logging

import ollama

log = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")

VALID_LABELS = {"relevant", "other", "irrelevant"}

CLASSIFICATION_PROMPT = """You are a query router for a legal search system whose ENTIRE dataset is
judgments from the Sindh High Court of Pakistan (admiralty/cargo disputes, civil suits, criminal
bail matters, compromise decrees, and similar).

Classify the user's question into exactly one label:

- "relevant": the question could plausibly be answered by looking up a Sindh High Court judgment
  (case facts, parties, judges, statutes cited, amounts, outcomes, case numbers, etc.), even if you
  don't know whether a matching judgment actually exists in the dataset.
- "other": the question is a genuine legal question, but clearly NOT about the Sindh High Court --
  e.g. it names a different court (Lahore High Court, Supreme Court, a US or Indian court), a
  different country's law, or asks a generic legal-definition question with no connection to a
  specific Sindh High Court case.
- "irrelevant": the question has no legal content at all -- general knowledge, recipes, tech
  support, small talk, etc.

Respond with ONLY the single word: relevant, other, or irrelevant. No punctuation, no explanation.

Examples:
Q: What was the outcome of the M.V. Miski cargo case?
A: relevant

Q: What was decided about the cargo aboard the M.V. Miski bound for the Port of Sudan?
A: relevant

Q: What case involved money being paid to the Nazir of the court?
A: relevant

Q: What are the requirements for filing a divorce in California?
A: other

Q: Summarize a recent Lahore High Court inheritance ruling.
A: other

Q: Can you recommend a good biryani recipe?
A: irrelevant

Q: What's the capital of France?
A: irrelevant

Now classify this question:
Q: {question}
A:"""


def _parse_label(raw_text: str) -> str | None:
    """Extract a valid label from the model's raw response, tolerating
    extra whitespace/punctuation/case."""
    cleaned = raw_text.strip().lower()
    cleaned = re.sub(r"[^a-z]", "", cleaned)
    return cleaned if cleaned in VALID_LABELS else None


def classify_query(query: str) -> str:
    """
    Returns one of "relevant", "other", "irrelevant". Fails open to
    "relevant" if the model's response can't be parsed, so a classifier
    hiccup blocks nothing -- the normal RAG "no information found" fallback
    already handles genuinely unanswerable questions safely.
    """
    prompt = CLASSIFICATION_PROMPT.format(question=query)

    try:
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response["message"]["content"]
    except Exception as exc:
        log.warning("Query classification failed (%s) -- defaulting to 'relevant'.", exc)
        return "relevant"

    label = _parse_label(raw_text)
    if label is None:
        log.warning("Unparseable classification response %r -- defaulting to 'relevant'.", raw_text)
        return "relevant"

    return label


def should_answer(label: str) -> bool:
    """True only for 'relevant' -- both 'other' and 'irrelevant' mean the
    system should decline rather than attempt a full RAG answer."""
    return label == "relevant"