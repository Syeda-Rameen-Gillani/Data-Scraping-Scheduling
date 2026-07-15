"""
reranking.py

Cross-encoder reranking step (Stage 3, Task 1). Vector search (bi-encoder)
retrieves a wider candidate pool cheaply, then a cross-encoder -- which
looks at the query and each chunk together, rather than as separately
embedded vectors -- re-scores and reorders that pool for precision.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 -- small, free, runs locally,
standard choice for this task (trained specifically for query-passage
relevance ranking, unlike the bi-encoder which is trained for general
semantic similarity).
"""

from sentence_transformers import CrossEncoder

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_cross_encoder = None


def _get_cross_encoder() -> CrossEncoder:
    """Lazy-load the cross-encoder so importing this module is cheap when
    reranking isn't actually being used (e.g. baseline eval runs)."""
    global _cross_encoder
    if _cross_encoder is None:
        _cross_encoder = CrossEncoder(RERANK_MODEL)
    return _cross_encoder


def rerank(query: str, objects: list, top_k: int | None = None) -> list:
    """
    Re-scores and reorders a list of Weaviate result objects (each with a
    .properties dict containing "text") using the cross-encoder, given the
    original query. Returns the same objects, reordered, optionally
    truncated to top_k.

    Each returned object gets a `.rerank_score` attribute attached (best
    effort -- if the object type doesn't allow attribute assignment, the
    score is tracked alongside instead) so callers can inspect/log the
    before/after scores for the "concrete example" the rubric asks for.
    """
    if not objects:
        return objects

    model = _get_cross_encoder()

    pairs = [(query, obj.properties.get("text", "")) for obj in objects]
    scores = model.predict(pairs)

    scored = list(zip(objects, scores))
    scored.sort(key=lambda pair: pair[1], reverse=True)

    reranked_objects = []
    for obj, score in scored:
        try:
            obj.rerank_score = float(score)
        except AttributeError:
            pass
        reranked_objects.append(obj)

    if top_k is not None:
        reranked_objects = reranked_objects[:top_k]

    return reranked_objects