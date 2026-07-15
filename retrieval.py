"""
retrieval.py

Core retrieval logic, kept separate from app.py (the FastAPI layer) so that
reranking, hybrid search, and query classification can each be added and
evaluated as independent, testable pieces rather than inline in the API
handler.

Schema note: field names here match the rebuilt Weaviate collection
(create_collection.py) for Stage 3's 33-field metadata, e.g. "file_name"
and "case_title" replace the old "case_code"/"case_no"/"topic" fields.
"""

import os
import re

from sentence_transformers import SentenceTransformer
from weaviate.classes.query import Filter
from weaviate_client import get_client

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
TOP_K = int(os.getenv("TOP_K", "5"))
WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

_embed_model = SentenceTransformer(EMBEDDING_MODEL)

CASE_NUMBER_PATTERN = re.compile(
    r"(?:[A-Za-z. ]+)?\d+/\d{4}",
    re.IGNORECASE,
)
CITATION_PATTERN = re.compile(
    r"\b\d{4}\s+[A-Z]{2,5}\s+\d+\b",
    re.IGNORECASE,
)

ARTICLE_PATTERN = re.compile(
    r"\b(article|section)\s+\d+[A-Za-z\-]*",
    re.IGNORECASE
)

JUDGE_PATTERNS = [
    re.compile(r"justice\s+([A-Za-z.\s]+)", re.I),
    re.compile(r"judge\s+([A-Za-z.\s]+)", re.I),
    re.compile(r"decided by\s+([A-Za-z.\s]+)", re.I),
    re.compile(r"before\s+([A-Za-z.\s]+)", re.I),
]

PARTY_PATTERN = re.compile(
    r"(?:cases involving|petitioner|respondent)\s+(.+)",
    re.I,
)

# Matches unspaced citation tokens like "2026SHC87" so they can be
# normalized to "2026 SHC 87" before BM25 tokenization -- see
# _normalize_query_for_keyword_search() below.
_UNSPACED_CITATION_PATTERN = re.compile(r"\b(\d{4})([A-Z]{2,5})(\d+)\b")

# Words that indicate a real question/sentence rather than a bare party
# name -- used to make detect_party_name() a bit less trigger-happy on
# short natural-language questions like "bail cases in Karachi".
_QUESTION_WORDS = {
    "what", "who", "when", "where", "why", "how", "did", "does", "is",
    "are", "was", "were", "cases", "case", "court", "courts", "recent",
}


def detect_case_number(query: str) -> str | None:
    """Detect a case-number-style reference in the query, e.g. '68/2013'."""
    match = CASE_NUMBER_PATTERN.search(query)
    return match.group() if match else None


def detect_citation(query: str) -> str | None:
    """
    Detect citations like:
        2026 SHC 87
        2025 SHC 104
    """
    match = CITATION_PATTERN.search(query)
    return match.group() if match else None


def detect_article(query: str) -> str | None:
    """
    Detect references like:
        Article 199
        Section 302
    """
    match = ARTICLE_PATTERN.search(query)
    return match.group() if match else None


def detect_judge(query):

    for pattern in JUDGE_PATTERNS:
        match = pattern.search(query)
        if match:
            return match.group(1).strip()

    return None


def detect_case_title(query: str) -> bool:
    """
    Heuristic:
    If the query contains 'vs', 'v.', or 'versus',
    treat it as a party-name search.
    """
    q = query.lower()

    return (
        " vs " in q
        or " v. " in q
        or " versus " in q
    )


def detect_party_name(query: str) -> bool:
    """
    If it isn't another structured query, and it doesn't read like a
    natural-language question, treat a short query as a possible bare
    party name (e.g. "Muhammad Ali" with no "vs"/case-number/etc).

    This is a heuristic and will sometimes be wrong in either direction --
    the real safety net is that _structured_lookup() falls back to
    semantic search whenever this guess doesn't actually find anything,
    so a misfire here costs one extra (fast) Weaviate call, not a wrong
    or empty final answer.
    """
    if detect_case_number(query):
        return False
    if detect_citation(query):
        return False
    if detect_article(query):
        return False
    if detect_judge(query):
        return False
    if detect_case_title(query):
        return False

    words = query.lower().split()
    if len(words) > 4:
        return False
    if any(w.strip("?.,!") in _QUESTION_WORDS for w in words):
        return False

    return True

def normalize_case_title(title):

    title = re.sub(r"\bversus\b", "vs", title, flags=re.I)
    title = re.sub(r"\bv\.\b", "vs", title, flags=re.I)
    title = re.sub(r"\bv\b", "vs", title, flags=re.I)

    return title.lower()

def lookup_by_case_number(case_id: str):
    """
    Exact metadata lookup by case number, bypassing semantic search entirely.
    Returns a Weaviate query result object (same shape as vector_search's).
    """
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=Filter.by_property("case_number").like(f"*{case_id}*"),
        )
        results.objects.sort(key=lambda obj: obj.properties.get("chunk_index", 0))
        return results
    finally:
        client.close()


def lookup_by_citation(citation: str):
    """
    Lookup citations like:
        2026 SHC 87
    """
    parts = citation.split()

    year = int(parts[0])
    journal = parts[1].upper()
    page = parts[2]

    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=(
                Filter.by_property("citation_year").equal(year)
                & Filter.by_property("citation_journal").equal(journal)
                & Filter.by_property("citation_page_number").equal(page)
            )
        )

        results.objects.sort(
            key=lambda obj: obj.properties.get("chunk_index", 0)
        )

        return results
    finally:
        client.close()


def lookup_by_judge(judge_name: str, top_k: int = TOP_K):
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=Filter.by_property("judge_names").like(f"*{judge_name}*"),
            limit=top_k,
        )
        return results
    finally:
        client.close()


def lookup_by_case_title(title: str, top_k: int = TOP_K):
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=Filter.by_property("case_title").like(f"*{title}*"),
            limit=top_k,
        )
        return results
    finally:
        client.close()


def lookup_by_party(party: str, top_k: int = TOP_K):
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=(
                Filter.by_property("petitioner_appellant").like(f"*{party}*")
                | Filter.by_property("respondent").like(f"*{party}*")
            ),
            limit=top_k,
        )
        return results
    finally:
        client.close()


def lookup_by_article(article: str, top_k: int = TOP_K):
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.fetch_objects(
            filters=Filter.by_property("articles_sections_cited").like(f"*{article}*"),
            limit=top_k,
        )
        return results
    finally:
        client.close()


def vector_search(query: str, top_k: int = TOP_K):
    """
    Plain semantic (vector) search over the chunk collection.
    Returns a Weaviate query result object.
    """
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        query_vector = _embed_model.encode(query).tolist()
        results = collection.query.near_vector(
            near_vector=query_vector,
            limit=top_k,
        )
        return results
    finally:
        client.close()


def hybrid_search(query: str, top_k: int = TOP_K, alpha: float = 0.5):
    """
    Combines BM25 keyword scoring with vector similarity, weighted by alpha
    (0 = pure keyword, 1 = pure vector, 0.5 = even mix). Uses Weaviate's
    native hybrid query -- since this collection stores externally-computed
    vectors (vectorizer_config=none), we supply both the query text (for
    BM25 tokenization) and the query vector explicitly.
    """
    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        query_vector = _embed_model.encode(query).tolist()
        results = collection.query.hybrid(
            query=query,
            vector=query_vector,
            alpha=alpha,
            limit=top_k,
        )
        return results
    finally:
        client.close()


def _normalize_query_for_keyword_search(query: str) -> str:
    """
    Insert spaces into unspaced citation-style tokens ("2026SHC87" ->
    "2026 SHC 87") before handing the query to BM25.

    Why this is needed: the corpus always stores citations space-separated
    ("2026 SHC 87" -- see citation_year/citation_journal/citation_page_number
    in create_collection.py). Weaviate's default BM25 tokenizer treats
    "2026SHC87" as a single opaque token, which won't match the three
    separate tokens "2026", "SHC", "87" in the stored text. Rather than
    reconfiguring Weaviate's tokenizer (a schema-level change that would
    affect every property), normalizing the query text at search time is
    a much smaller, localized fix -- and it's symmetric with how
    detect_citation()'s regex already expects a spaced format for the
    exact-lookup path.
    """
    return _UNSPACED_CITATION_PATTERN.sub(r"\1 \2 \3", query)


# Properties BM25 searches over, with boosts (Weaviate's "property^weight"
# syntax). Chosen deliberately rather than searching every property with
# equal weight:
#   - case_number (^3) and case_title (^2): short, structured fields where
#     a keyword hit is a near-exact identifier match, not just a topical
#     overlap -- should dominate the ranking when it fires.
#   - judge_names (^2), legal_keywords (^2): judge name matches and
#     LLM-curated keyword matches are also strong, specific signals.
#   - short_summary, head_note: LLM-synthesized condensed text; a keyword
#     match here usually reflects the judgment's actual subject matter.
#   - text (base weight): the full chunk content -- broadest coverage,
#     but also the noisiest (see DECISIONS.md's BM25-on-small-corpus
#     finding), so it isn't boosted above the more specific fields.
KEYWORD_SEARCH_PROPERTIES = [
    "case_number^3",
    "case_title^2",
    "judge_names^2",
    "legal_keywords^2",
    "short_summary",
    "head_note",
    "text",
]


def keyword_search(query: str, top_k: int = TOP_K):
    """
    Pure keyword (BM25) search -- no vector component at all. This is
    what lets keyword search be evaluated independently, per the brief's
    requirement that keyword, semantic, and hybrid each be independently
    invokable and comparable head-to-head.
    """
    normalized_query = _normalize_query_for_keyword_search(query)

    client = get_client()
    collection = client.collections.get(WEAVIATE_COLLECTION)

    try:
        results = collection.query.bm25(
            query=normalized_query,
            query_properties=KEYWORD_SEARCH_PROPERTIES,
            limit=top_k,
        )
        return results
    finally:
        client.close()


def _structured_lookup(query: str, top_k: int = TOP_K):
    """
    Shared routing logic for ALL THREE retrieval strategies (retrieve,
    retrieve_hybrid, retrieve_reranked) so a given query gets the SAME
    structured-lookup treatment no matter which strategy handles it --
    they should only differ in what they do for the final semantic-search
    fallback (plain vector / hybrid / reranked).

    Tries detectors in priority order (most exact match first): citation,
    case number, judge, article/section, case title, bare party name.
    Returns the Weaviate result object for the FIRST detector that both
    matches AND returns at least one object.

    Returns None if nothing matched, OR if every detector that matched
    still came back with zero objects (e.g. the judge's name is stored
    with different formatting than the query used) -- callers should
    fall back to semantic/hybrid/reranked search in that case rather than
    handing back an empty result to the user.
    """
    citation = detect_citation(query)
    if citation:
        result = lookup_by_citation(citation)
        if result.objects:
            return result

    case_id = detect_case_number(query)
    if case_id:
        result = lookup_by_case_number(case_id)
        if result.objects:
            return result

    judge = detect_judge(query)
    if judge:
        result = lookup_by_judge(judge, top_k=top_k)
        if result.objects:
            return result

    article = detect_article(query)
    if article:
        result = lookup_by_article(article, top_k=top_k)
        if result.objects:
            return result

    if detect_case_title(query):
        result = lookup_by_case_title(query, top_k=top_k)
        if result.objects:
            return result

    if detect_party_name(query):
        result = lookup_by_party(query, top_k=top_k)
        if result.objects:
            return result

    return None


def retrieve(query: str, top_k: int = TOP_K):
    """
    Main entry point: routes through the shared structured-lookup
    detectors, falling back to plain semantic vector search if nothing
    structured matched (or matched but found nothing).
    """
    structured = _structured_lookup(query, top_k=top_k)
    if structured is not None:
        return structured
    return vector_search(query, top_k=top_k)


def retrieve_keyword(query: str, top_k: int = TOP_K):
    """
    Same routing as retrieve(), but falls back to pure keyword (BM25)
    search instead of vector search. This is the standalone keyword
    strategy the brief requires be independently evaluable alongside
    semantic and hybrid.
    """
    structured = _structured_lookup(query, top_k=top_k)
    if structured is not None:
        return structured
    return keyword_search(query, top_k=top_k)


def retrieve_hybrid(query: str, top_k: int = TOP_K, alpha: float = 0.5):
    """
    Same routing as retrieve(), but falls back to hybrid (BM25 + vector)
    search instead of plain vector search.
    """
    structured = _structured_lookup(query, top_k=top_k)
    if structured is not None:
        return structured
    return hybrid_search(query, top_k=top_k, alpha=alpha)


def retrieve_reranked(query: str, top_k: int = TOP_K, candidate_pool: int = 15):
    """
    Same routing as retrieve(), but the semantic-search fallback first
    pulls a wider candidate pool (candidate_pool > top_k) and reranks it
    with a cross-encoder before truncating to top_k. Candidate pool is
    wider than top_k on purpose: a bi-encoder's top-5 by cosine similarity
    leaves little room for a reranker to do anything -- widening to e.g.
    15 gives the cross-encoder actual borderline candidates to re-order.

    Structured lookups (citation/case-number/judge/article/title/party)
    are NOT reranked -- those are exact metadata matches, not
    relevance-ranked semantic results, so cross-encoder scoring doesn't
    apply to them.
    """
    from reranking import rerank  # local import: avoids loading the cross-encoder model for callers that never rerank

    structured = _structured_lookup(query, top_k=top_k)
    if structured is not None:
        return structured

    results = vector_search(query, top_k=candidate_pool)
    results.objects = rerank(query, results.objects, top_k=top_k)
    return results