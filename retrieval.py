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
from query_classifier import classify_query

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
TOP_K = int(os.getenv("TOP_K", "5"))
WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

_embed_model = SentenceTransformer(EMBEDDING_MODEL)

CASE_NUMBER_PATTERN = re.compile(r"\d+/\d{4}")


def detect_case_number(query: str) -> str | None:
    """Detect a case-number-style reference in the query, e.g. '68/2013'."""
    match = CASE_NUMBER_PATTERN.search(query)
    return match.group() if match else None


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


def retrieve_hybrid(query: str, top_k: int = TOP_K, alpha: float = 0.5):
    """
    Same routing as retrieve(): exact case-number lookup if the query
    contains one, otherwise hybrid (BM25 + vector) search.
    """
    case_id = detect_case_number(query)
    if case_id:
        return lookup_by_case_number(case_id)
    return hybrid_search(query, top_k=top_k, alpha=alpha)


def retrieve(query: str, top_k: int = TOP_K):
    """
    Main entry point: routes to exact case-number lookup if the query
    contains one, otherwise falls back to semantic vector search.
    """
    case_id = detect_case_number(query)
    if case_id:
        return lookup_by_case_number(case_id)
    return vector_search(query, top_k=top_k)


def retrieve_reranked(query: str, top_k: int = TOP_K, candidate_pool: int = 15):
    """
    Same routing as retrieve(), but for the vector-search path, first pulls
    a wider candidate pool (candidate_pool > top_k) and reranks it with a
    cross-encoder before truncating to top_k. Candidate pool is wider than
    top_k on purpose: a bi-encoder's top-5 by cosine similarity leaves little
    room for a reranker to do anything -- widening to e.g. 15 gives the
    cross-encoder actual borderline candidates to re-order.

    Case-number lookups are NOT reranked -- that path is an exact metadata
    match, not a relevance-ranked semantic result, so cross-encoder scoring
    doesn't apply.
    """
    from reranking import rerank  # local import: avoids loading the cross-encoder model for callers that never rerank

    case_id = detect_case_number(query)
    if case_id:
        return lookup_by_case_number(case_id)

    results = vector_search(query, top_k=candidate_pool)
    results.objects = rerank(query, results.objects, top_k=top_k)
    return results

def retrieve_with_classification(query: str, top_k: int = TOP_K):

    if classify_query(query) == "irrelevant":
        return None

    return retrieve(query, top_k)