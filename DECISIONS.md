# DECISIONS.md

# Stage 3 – Advanced Retrieval & Evaluation

## Overview

This stage extended the existing Retrieval-Augmented Generation (RAG) pipeline with three independent retrieval improvements:

* Cross-encoder reranking
* Hybrid retrieval (Vector + BM25)
* Query classification

Each component was implemented as a separate module so it could be evaluated independently. Performance was measured using a self-authored evaluation set instead of relying on subjective observations.

---

# 1. Cross-Encoder Reranking

## Decision

A cross-encoder reranker was added after semantic retrieval.

The retrieval pipeline first retrieves the top 15 candidate chunks using vector search. Those candidates are then rescored by a cross-encoder before returning the final top 5 results.

Using a larger candidate pool gives the reranker meaningful alternatives to compare rather than simply rescoring an already tiny result set.

---

## Evaluation

**Note on eval set history:** the first version of this evaluation (10 relevant + 5 irrelevant questions) hit a ceiling effect -- vector search already returned the correct document at rank 1 for every question, so reranking had nothing to fix. Three additional deliberately-ambiguous questions were added afterward (see eval_set.py), each targeting judgments that share overlapping vocabulary (cargo, vessel, security, the court's "Nazir"). The numbers below are from that harder 18-question set (13 of which have a retrievable expected judgment); see evaluation_results/eval_20260708_155949.json for the raw run.

### Baseline (Vector Search, top_k=5)

* Hit Rate@5: **76.9%** (10/13)
* MRR: **0.692**

### After Reranking (candidate_pool=15, top_k=5)

* Hit Rate@5: **92.3%** (12/13)
* MRR: **0.808**

---

## Interpretation

On the harder eval set, reranking measurably helps: Hit Rate@5 improved from 76.9% to 92.3%, and MRR from 0.692 to 0.808. Two of the three deliberately-ambiguous questions that vector search missed were fixed by the cross-encoder -- "What case involved money being paid to the Nazir of the court?" and "Tell me about a case where security had to be furnished to release a vessel or cargo" both moved from a miss to a hit.

One ambiguous question still misses after reranking: "What happened in the admiralty case involving a cargo shortage?" (expected case 159974cfms-dc83; both baseline and reranked instead surface 159976cfms-dc83, a different but near-consecutive case ID from the same filing batch). See "Where all three strategies still fail" below -- this looks like two genuinely similar judgments rather than a ranking-algorithm problem, so it's unlikely reranking alone can fix it.

The original (pre-expansion) run is preserved here for transparency about how the eval set evolved: on the original 10-question set, Hit Rate@5 and MRR were 100%/1.000 for both baseline and reranked -- a ceiling effect from a small, mostly-distinct-topic corpus, not evidence that reranking doesn't help. The expanded set was specifically designed to test that, and shows that it does.

---

# 2. Hybrid Search (Vector + BM25)

## Decision

Hybrid retrieval was implemented using Weaviate's native Hybrid Search.

Semantic vector similarity was combined with BM25 keyword matching using an alpha value of 0.5.

The motivation was to combine semantic understanding with exact keyword matching so that legal terminology, names, statutes, and case numbers could contribute to retrieval.

---

## Evaluation

Same eval-set-expansion note as the reranking section above applies here. Numbers below are from the current 18-question set (evaluation_results/eval_20260708_155949.json).

### Vector Search (baseline)

* Hit Rate@5: **76.9%** (10/13)
* MRR: **0.692**

### Hybrid Search (alpha=0.5)

* Hit Rate@5: **92.3%** (12/13)
* MRR: **0.795**

---

## Interpretation

Hybrid retrieval also improves over baseline on the harder eval set -- the same two ambiguous questions that vector search missed (the Nazir-payment question and the security-furnished-for-vessel-release question) are fixed by adding BM25 into the mix. Hit Rate@5 matches reranking exactly (92.3%), though MRR is marginally lower than reranking's (0.795 vs 0.808) -- on this eval set, the cross-encoder edges out BM25 fusion slightly, though both are clear improvements over vector search alone.

The one still-missed question is the same admiralty cargo-shortage query that reranking also fails on (see "Where all three strategies still fail" below).

**Historical negative result, kept for transparency:** on the original 10-question set (before the ambiguous questions were added), hybrid search actually *reduced* MRR to 0.962 versus vector search's 1.000. Investigation at the time found BM25 preferring an unrelated judgment due to generic procedural terms (Plaintiff, Defendant, Court) receiving unstable IDF weight on a corpus of only ~8-10 documents. That finding is still true as a general statement about BM25 on very small corpora -- it just no longer describes the current larger, harder eval set, where hybrid's vector component and the added BM25 signal together net out as a clear improvement rather than a regression. This is a good example of why a fixed, ceiling-prone eval set can produce a misleading negative result: the fix wasn't to the retrieval code, it was to the eval set's difficulty.

---

# 3. Query Classification

## Decision

A query classifier was added before retrieval.

Incoming questions are classified into one of three categories:

* **relevant**
* **other**
* **irrelevant**

Only relevant queries continue through the RAG pipeline.

Questions classified as other or irrelevant are rejected before retrieval and receive an explanatory response.

---

## Definition of Categories

### Relevant

Questions that could reasonably be answered using the Sindh High Court judgments contained in the corpus.

Examples include:

* case facts
* judges
* parties
* case numbers
* statutes
* outcomes
* monetary amounts

---

### Other

Legal questions that fall outside the scope of this dataset.

Examples include:

* Lahore High Court cases
* Supreme Court cases
* foreign jurisdictions
* general legal concepts

---

### Irrelevant

Questions unrelated to the legal corpus.

Examples include:

* recipes
* technical support
* general knowledge
* casual conversation

---

## Evaluation

Questions evaluated: **18**
Correct classifications: **15**
Accuracy: **83.3%** (15/18)
False positives: **1**
False negatives: **2**

**Important caveat -- run-to-run non-determinism (found and fixed):** re-running evaluate_classification.py against an unchanged eval set produced different accuracy numbers on different runs (one saved run shows 100%, another shows 83.3% -- see evaluation_results/classifier_eval_*.json). The cause was that classification.py's ollama.chat() call didn't set temperature, so it used Ollama's default (non-zero) sampling temperature -- the same question could get a different label from run to run purely from sampling variance, not from any change in the corpus or the prompt. This has been fixed by setting `options={"temperature": 0}` on the classification call, so the 83.3% figure above should now be reproducible. Re-run evaluate_classification.py after pulling this fix to confirm before relying on this number for a final submission.

---

## Failure Modes

Two relevant Sindh High Court questions were incorrectly classified as "other":

* the M.V. Miski cargo dispute
* the Nazir payment query

The classifier also incorrectly labeled one unrelated query ("Can you recommend a good biryani recipe?") as relevant.

These failures indicate that the local 3B language model occasionally relies on surface vocabulary (e.g. generic legal-sounding phrasing) rather than reliably checking whether a question maps to a judgment actually in this corpus.

**Unverified hypothesis, flagged as such rather than stated as fact:** the two misclassified questions both involve the Nazir/M.V. Miski cargo topics, which also gave vector search the most trouble in the retrieval evaluation (the "Nazir of the court" and "security furnished" ambiguous questions). It's tempting to connect these -- same underlying vocabulary overlap making both retrieval and classification less confident -- but the specific run that produced these two failure examples wasn't saved with per-question detail (only a later, cleaner 100%-accuracy run was persisted to evaluation_results/), so this connection can't actually be confirmed against saved data. Re-running evaluate_classification.py with the temperature=0 fix and checking whether the same two questions fail consistently would either support or rule this out -- worth doing before stating it as a real finding in the submission.

---

# 4. Metadata Extraction Observations

Metadata was generated locally using the **llama3.2:3b** model.

Most judgments were processed successfully. However, approximately one extraction returned malformed JSON containing additional text after the expected object.

Instead of terminating the ingestion process, the parser fell back to null metadata values for that judgment while allowing the remainder of the pipeline to continue successfully.

During manual verification against the original judgments, several metadata inaccuracies were identified, including:

* Misinterpreting South Asian digit grouping (for example, Rs. 2,40,30,000 being interpreted incorrectly).
* Confusing the amount claimed in litigation with the amount actually decreed by the court.
* Minor inconsistencies in identifying legal representatives and parties.

Rather than relying solely on LLM-generated metadata, every evaluation question and expected answer was verified directly against the original judgment PDFs before being included in the evaluation set.

---

# 5. Dataset Observations

While scraping the Sindh High Court website, many case listings did not contain downloadable PDF judgments.

These were primarily administrative listings without attached judgments.

As a result, only a subset of the available listings could be ingested into the retrieval corpus.

This was determined to be a characteristic of the source website rather than a scraper or ingestion failure.

---

# 6. Evaluation Methodology

A self-authored evaluation set containing **18 questions** was created.

The evaluation includes:

* Relevant Sindh High Court questions
* Off-domain legal questions
* Completely unrelated questions
* Deliberately ambiguous legal questions

Retrieval quality was measured using:

* Hit Rate@5
* Mean Reciprocal Rank (MRR)

Classification quality was measured using:

* Accuracy
* False Positives
* False Negatives

Each retrieval improvement was evaluated independently to isolate its effect on overall system performance.

---

# 7. Where All Three Strategies Still Fail

One question is missed by baseline vector search, reranking, AND hybrid search alike:

> "What happened in the admiralty case involving a cargo shortage?"
> Expected: case 159974cfms-dc83 (short-landed cargo dispute)
> All three strategies instead surface case 159976cfms-dc83 as the top result.

These two case codes are from the same filing batch (159973/159974/159976, all suffixed `cfms-dc83`) -- almost certainly consecutive admiralty judgments filed together, likely with very similar boilerplate and subject matter (both plausibly involve short-landed/damaged cargo claims). Our hypothesis: this isn't a ranking-algorithm problem at all -- the two judgments are genuinely close in content, so a bi-encoder, a cross-encoder, and BM25 all agree on the wrong-but-legitimately-similar neighbor. Reranking and hybrid search can reorder candidates that are already in the pool, but they can't manufacture a semantic distinction the underlying documents don't clearly have. Fixing this would likely need either richer per-chunk metadata to disambiguate (e.g. surfacing the specific cargo/vessel name in the chunk itself, which Stage 3's 33-field enrichment now provides and could be leveraged more directly in the query or reranker prompt) or a query that names the distinguishing fact more specifically.

---

# 8. Summary

| Component               | Result (18-question eval set, evaluation_results/eval_20260708_155949.json)                    |
| ----------------------- | ------------------------------------------------------------------------------------------------ |
| Vector Search (baseline)| Hit Rate@5 76.9% (10/13), MRR 0.692                                                                |
| Cross-Encoder Reranking | Hit Rate@5 92.3% (12/13), MRR 0.808 -- clear improvement; fixed 2 of 3 ambiguous-question misses  |
| Hybrid Search           | Hit Rate@5 92.3% (12/13), MRR 0.795 -- matches reranking's Hit Rate, slightly lower MRR           |
| Query Classification    | 83.3% accuracy (15/18); non-determinism bug found and fixed (temperature=0) -- re-run to confirm  |

---

# Conclusion

The retrieval pipeline was extended with reranking, hybrid retrieval, and query classification, each implemented and evaluated as an independently-callable strategy (see retrieval.py / evaluate.py).

The eval set went through one important revision worth being transparent about: the original 10-question set hit a ceiling (100% Hit Rate/MRR for every strategy), because vector search alone already got everything right on a small, mostly-distinct-topic corpus -- leaving reranking and hybrid nothing to improve, and even making hybrid's real limitation (unstable BM25 IDF weighting on ~8-10 documents) look like a pure regression. Three deliberately-ambiguous questions were added specifically to break that ceiling. On the resulting harder set, both reranking and hybrid show clear, genuine improvements over baseline vector search (76.9% -> 92.3% Hit Rate@5 for both), with reranking narrowly ahead on MRR. One question still defeats all three strategies, and the likely explanation is two genuinely similar judgments rather than a fixable ranking issue -- see Section 7.

The query classifier's accuracy number was found to be non-reproducible between runs due to an unset LLM sampling temperature; this has been fixed, and the 83.3% figure should be re-confirmed with a fresh run before final submission.

Retained rather than smoothed over: the original hybrid-search regression finding, the ceiling-effect explanation for why the eval set needed expanding, the classifier's non-determinism bug, and the one persistent retrieval miss with a stated (not proven) hypothesis. Per the project's own standard, an explained negative result -- or an honestly-flagged unresolved one -- is worth more than a claimed improvement without a mechanism.

---

# 9. Stage 4 Addendum — Chat Tool-Calling, Tool Filters, and Documentation Cleanup

This section documents what changed when the project was brought in line with the Stage 4 brief
after an initial review flagged several gaps. Recorded here rather than silently fixed, per this
project's own standard for negative/gap disclosure.

## 9.1 — Tool contract now actually applies its filters

`search_judgments(query, strategy, top_k, court, year, judge)` previously accepted `court`/`year`/
`judge` per the Section 5.1 tool contract but never passed them to the retrieval layer -- they were
silently dropped. `retrieval.py` now has a shared `build_metadata_filter()` that turns these into a
Weaviate `Filter` (via `Filter.by_property(...).like()`/`.equal()`), threaded through
`vector_search()`, `hybrid_search()`, `keyword_search()`, and all three `retrieve*()` wrappers.
Filters are applied only on the semantic/keyword/hybrid fallback path, not on the structured-lookup
detectors -- those already do their own exact metadata matching, so a second filter layered on top
would only make an already-exact match stricter for no benefit.

Known limitation carried over from Section 7's citation gap: a `year` filter against
`citation_year` will return zero results for the current corpus, since that field is `None` for
every ingested judgment. This is a corpus gap (see Negative Results in `COMPARISON.md`), not a bug
in the new filter code.

## 9.2 — Session transcript added

Section 9 of the brief requires a short session transcript showing tool-call vs no-tool-call turns.
None existed. `SESSION_TRANSCRIPT.md` now covers five turns: a greeting (no tool call), a case
question (tool call), a same-topic follow-up answered from history (no new tool call), a topic
shift (new tool call), and an off-domain query rejected by the classifier before retrieval. It's
explicitly marked as reconstructed from real corpus content and the actual code paths, not a
captured live run, since this environment has no access to the Ollama/Weaviate/Gemini services the
project depends on -- it should be replaced with a real captured transcript before final submission.

## 9.3 — COMPARISON.md rewritten

The previous version of `COMPARISON.md` had several problems: leftover conversational commentary
that read like an unedited AI chat reply, a missing Negative Results section (required and
explicitly called out in the brief as something not to skip), a citation example ("2026 SHC 87")
that isn't backed by any real judgment in this corpus, and a classifier accuracy claim (100%, 31
questions, 0 FP/FN) with no corresponding file in `evaluation_results/` to verify it against --
directly contradicting this file's own 83.3%/18-question figure. It's been rewritten to:

- use only numbers traceable to `evaluation_results/eval_20260714_210619.json`
- pull every "strategy X wins" example from that file's actual per-question ranks, rather than
  illustrative ones
- add the required Negative Results section
- flag, rather than paper over, that only 2 of the requested 3 "hybrid beats both" examples
  actually exist in the current eval set
- replace the stale "cargo shortage" all-strategies-failure example with the one that's actually
  still unsolved in the current 25-question run (hybrid now recovers the cargo-shortage case at
  rank 2)
- present the classifier section honestly: the 18-question/83.3% figure is the only one with a
  real file behind it, and the 100% figure should not be submitted until `evaluate_classification.py`
  is re-run against the current 31-question set and its output saved

## 9.4 — Dead code removed

`query_classifier.py` (a rule-based classifier from an earlier draft) was never imported by
anything -- `classification.py`'s LLM-based classifier is what `tools.py` actually uses. Removed to
avoid a reviewer wondering which one is live.

## 9.5 — Still outstanding

- Re-run `evaluate_classification.py` against the current 31-question `EVAL_SET` with the
  temperature=0 fix confirmed in effect, and save the result to `evaluation_results/`.
- Replace `SESSION_TRANSCRIPT.md` with a real captured transcript once the services are running.
- Commit these changes on a dedicated stage-4 branch and open the PR (current repo state has these
  changes uncommitted on `submission-stage3`, whose last commit is still "Complete Stage 3...").
- Consider adding one more eval question specifically targeting the "hybrid beats both individually"
  gap (see Negative Results item 5 in `COMPARISON.md`).