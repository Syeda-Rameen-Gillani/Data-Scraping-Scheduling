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

### Baseline (Vector Search)

* Hit Rate@5: **100%**
* MRR: **1.000**

### After Reranking

* Hit Rate@5: **100%**
* MRR: **1.000**

---

## Interpretation

No measurable improvement was observed in the aggregate metrics.

This was expected because the evaluation corpus contains only eight real judgments. Vector search already returned the correct document at rank one for every retrieval question, leaving no incorrect top result for the reranker to correct.

Although the metrics remained unchanged, reranking did modify the ordering of lower-ranked candidates.

For example, one ambiguous admiralty query originally produced the ranking:

Document A → Document B → Document C

After reranking the order became:

Document A → Document C → Document B

This demonstrates that the cross-encoder independently rescored retrieved candidates even though the highest-ranked document remained unchanged.

One important observation is that reranking operated on a larger candidate pool (15 candidates versus the baseline 5). Therefore, some ranking differences resulted from considering additional candidates rather than the cross-encoder alone. Both factors contributed to the final ranking.

---

# 2. Hybrid Search (Vector + BM25)

## Decision

Hybrid retrieval was implemented using Weaviate's native Hybrid Search.

Semantic vector similarity was combined with BM25 keyword matching using an alpha value of 0.5.

The motivation was to combine semantic understanding with exact keyword matching so that legal terminology, names, statutes, and case numbers could contribute to retrieval.

---

## Evaluation

### Vector Search

* Hit Rate@5: **100%**
* MRR: **1.000**

### Hybrid Search

* Hit Rate@5: **100%**
* MRR: **0.962**

---

## Interpretation

Hybrid retrieval slightly reduced ranking quality.

Investigation showed that BM25 consistently preferred an unrelated judgment because of generic procedural legal terms such as:

* Plaintiff
* Defendant
* Court
* Consideration

Since the corpus contains only eight judgments, BM25's IDF statistics are unstable and these common legal words received disproportionately high scores.

For the M.V. Miski query, pure vector search correctly ranked the target judgment first, whereas BM25 returned five chunks from an unrelated judgment. The hybrid search therefore lowered the correct document's position.

This is a known limitation of BM25 on very small datasets rather than an implementation issue.

A larger corpus would provide more reliable keyword statistics and would likely improve hybrid retrieval performance.

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

Questions evaluated:

* **18**

Correct classifications:

* **15**

Accuracy:

* **100%**
it varies sometimes due to ollama

False positives:

* **1**

False negatives:

* **2**

---

## Failure Modes

Two relevant Sindh High Court questions were incorrectly classified as "other."

Examples included:

* the M.V. Miski cargo dispute
* the Nazir payment query

The classifier also incorrectly labeled one unrelated query ("Can you recommend a good biryani recipe?") as relevant.

These failures indicate that the local 3B language model occasionally relies on surface vocabulary rather than accurately determining whether a question belongs to the corpus.

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

# 7. Summary

| Component               | Result                                                                       |
| ----------------------- | ---------------------------------------------------------------------------- |
| Vector Search           | Baseline retrieval system                                                    |
| Cross-Encoder Reranking | No aggregate metric improvement; reordered lower-ranked candidates           |
| Hybrid Search           | Slight decrease in MRR due to unstable BM25 weighting on a very small corpus |
| Query Classification    | 83.3% accuracy with identifiable and explainable failure modes               |

---

# Conclusion

The retrieval pipeline was successfully extended with reranking, hybrid retrieval, and query classification while maintaining a modular architecture in which each component could be evaluated independently.

Not every enhancement improved quantitative performance. Reranking reached a ceiling effect because the baseline vector retrieval already retrieved the correct document first for every evaluation query. Hybrid retrieval slightly reduced ranking quality because BM25 keyword statistics were unreliable on a corpus of only eight judgments.

Rather than omitting these results, they were retained and analyzed to understand why they occurred. This provides a transparent evaluation of the system and highlights practical limitations of retrieval techniques on small legal corpora.
