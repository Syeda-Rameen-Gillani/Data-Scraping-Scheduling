"""
evaluate.py

Evaluation harness for Stage 3. Runs the self-authored eval set (eval_set.py)
against the current retrieval pipeline and reports Hit Rate and MRR, so that
reranking/hybrid search can each be measured with a real before/after number
rather than a subjective impression.

Deliberately calls retrieval.retrieve() directly rather than the /chat
endpoint -- the LLM generation step (Ollama) is the slow, non-deterministic
part and isn't what reranking/hybrid search actually change. Bypassing it
keeps a full eval run to a few seconds instead of ~15-30 minutes.
"""

import json
from datetime import datetime

from eval_set import EVAL_SET
from retrieval import retrieve, retrieve_reranked, retrieve_hybrid

TOP_K = 5


def get_ranked_file_names(query: str, retrieve_fn=retrieve, top_k: int = TOP_K) -> list[str]:
    """
    Runs retrieval for one query and returns the distinct file_names in
    the order they were returned (i.e. relevance-ranked).
    """
    results = retrieve_fn(query, top_k=top_k)
    ranked = []
    for obj in results.objects:
        file_name = obj.properties.get("file_name")
        if file_name and file_name not in ranked:
            ranked.append(file_name)
    return ranked


def evaluate(label: str = "", retrieve_fn=retrieve, top_k: int = TOP_K, verbose: bool = True) -> dict:
    """
    Runs every retrieval-labeled question in EVAL_SET (i.e. every question
    with an expected_file_name) and computes Hit Rate @ k and MRR.

    Questions with expected_file_name=None (the off-domain/irrelevant set)
    are skipped here -- they belong to query-classification evaluation,
    not retrieval evaluation, and are scored separately.
    """
    retrieval_questions = [q for q in EVAL_SET if q.get("expected_file_name")]

    hits = 0
    reciprocal_ranks = []
    details = []

    for item in retrieval_questions:
        ranked = get_ranked_file_names(item["question"], retrieve_fn=retrieve_fn, top_k=top_k)
        expected = item["expected_file_name"]

        if expected in ranked:
            rank = ranked.index(expected) + 1
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            rank = None
            reciprocal_ranks.append(0.0)

        details.append({
            "question": item["question"],
            "expected": expected,
            "retrieved": ranked,
            "rank": rank,
        })

    n = len(retrieval_questions)
    hit_rate = hits / n if n else 0.0
    mrr = sum(reciprocal_ranks) / n if n else 0.0

    if verbose:
        print(f"\n=== Retrieval evaluation: {label} ===")
        print(f"Questions evaluated: {n}")
        print(f"Hit Rate @ {top_k}: {hit_rate:.1%}  ({hits}/{n})")
        print(f"MRR: {mrr:.3f}")
        print()
        for d in details:
            status = "HIT " if d["expected"] in d["retrieved"] else "MISS"
            print(f"[{status}] rank={d['rank']}  {d['question']}")
            print(f"       expected : {d['expected']}")
            print(f"       retrieved: {d['retrieved']}")
        print()

    return {"label": label, "hit_rate": hit_rate, "mrr": mrr, "n": n, "details": details}


if __name__ == "__main__":
    import os

    baseline = evaluate(label="baseline (vector-only, top_k=5)", retrieve_fn=retrieve, top_k=5)

    reranked = evaluate(
        label="vector + cross-encoder rerank (candidate_pool=15, top_k=5)",
        retrieve_fn=retrieve_reranked,
        top_k=5,
    )

    hybrid = evaluate(
        label="hybrid (BM25 + vector, alpha=0.5, top_k=5)",
        retrieve_fn=retrieve_hybrid,
        top_k=5,
    )

    print("=== Summary ===")
    print(f"Baseline  -- Hit Rate: {baseline['hit_rate']:.1%}  MRR: {baseline['mrr']:.3f}")
    print(f"Reranked  -- Hit Rate: {reranked['hit_rate']:.1%}  MRR: {reranked['mrr']:.3f}")
    print(f"Hybrid    -- Hit Rate: {hybrid['hit_rate']:.1%}  MRR: {hybrid['mrr']:.3f}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("evaluation_results", exist_ok=True)
    output_file = os.path.join("evaluation_results", f"eval_{timestamp}.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "baseline": baseline,
                "reranked": reranked,
                "hybrid": hybrid,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nEvaluation results saved to: {output_file}")