# Executive Summary

This project implemented four retrieval configurations over a corpus of Sindh High Court judgments: keyword search (BM25), semantic vector search, semantic search with cross-encoder reranking, and hybrid retrieval combining keyword and semantic search. A query classifier was also implemented to detect and reject irrelevant or off-domain questions before retrieval.

Evaluation was performed on a dataset of 25 legal retrieval queries and 31 classification queries. Among all retrieval strategies, the hybrid approach achieved the strongest overall performance with a Precision@1 of 0.76, Precision@5 of 0.88, and Mean Reciprocal Rank (MRR) of 0.82 while maintaining acceptable query latency. Keyword search remained highly effective for exact citation, case number, and party-name lookups, whereas semantic retrieval improved performance on paraphrased legal questions. The hybrid strategy successfully combined the strengths of both approaches, producing the highest retrieval accuracy across the evaluation set.

The query classifier achieved 100% accuracy by correctly identifying all 26 relevant queries and rejecting all 5 irrelevant queries without any false positives. These results demonstrate that combining structured keyword retrieval with semantic vector search provides the most robust and reliable search experience for Sindh High Court judgments.


| Strategy          |      P@1 |      P@5 |      MRR | Avg Latency |
| ----------------- | -------: | -------: | -------: | ----------: |
| Keyword           |     0.72 |     0.84 |     0.78 |     4444 ms |
| Baseline Semantic |     0.56 |     0.76 |    0.653 |     5605 ms |
| Reranked Semantic |     0.64 |     0.84 |    0.733 |     7084 ms |
| **Hybrid**        | **0.76** | **0.88** | **0.82** | **5467 ms** |

This changes our conclusion.

Previously you had mentioned Hybrid underperformed, but **your final evaluation clearly shows Hybrid is the best retrieval strategy overall.**

* Highest Precision@1 ✅
* Highest Precision@5 ✅
* Highest MRR ✅
* Moderate latency (much faster than reranking)

That is actually a very nice result for your report.

---

# Classification Results

These are excellent.

| Metric              | Value    |
| ------------------- | -------- |
| Queries             | 31       |
| Relevant            | 26       |
| Irrelevant          | 5        |
| Accuracy            | **100%** |
| Rejection Rate      | **100%** |
| False Positive Rate | **0%**   |

Confusion Matrix

|                   | Pred Relevant | Pred Irrelevant |
| ----------------- | ------------: | --------------: |
| Actual Relevant   |            26 |               0 |
| Actual Irrelevant |             0 |               5 |

## Keyword Search

### Implementation

Keyword retrieval was implemented using BM25 to perform exact lexical matching over the indexed judgment corpus. The index contains structured metadata including case titles, case numbers, citations, judge names, statutes, and judgment text. Query preprocessing normalizes legal citations so that common citation formats can still be matched reliably.

### Strengths

Keyword search performed particularly well for structured queries where users supplied explicit identifiers. Exact citations, case numbers, party names, and judge names were typically retrieved as the highest-ranked result because BM25 directly matches important legal terms.

Evaluation showed:

* Precision@1: **0.72**
* Precision@5: **0.84**
* Mean Reciprocal Rank (MRR): **0.78**
* Average Latency: **4444 ms**

Keyword retrieval also produced the lowest average latency among all evaluated retrieval strategies, making it the fastest approach.

### Weaknesses

Performance decreased when users described legal issues without using the exact wording contained in the judgments. Since BM25 relies on lexical overlap rather than semantic similarity, paraphrased legal questions often retrieved partially related judgments instead of the intended case.

### Advantages

* Fastest retrieval strategy.
* Excellent performance for exact case lookups.
* Reliable for citations, statutes, judges, and party names.
* Simple and computationally inexpensive.

### Limitations

* Cannot understand semantic meaning.
* Sensitive to vocabulary differences.
* Performance declines on descriptive natural-language legal questions.

## Semantic Search

### Implementation

Semantic retrieval was implemented using dense vector embeddings generated with the **all-MiniLM-L6-v2** Sentence Transformer model. Judgment documents were chunked before embedding, and the resulting vectors were stored in **Weaviate** together with structured metadata such as case number, citation, case title, judge, and decision date. Queries were embedded into the same vector space, allowing retrieval based on semantic similarity rather than exact keyword matching.

An additional experiment was conducted using a **Cross-Encoder reranker**, which re-ranked the top candidate passages returned by the vector search to improve result ordering.

### Strengths

Semantic retrieval demonstrated its greatest advantage on natural-language legal questions where the user's wording differed from the wording used in the judgment. By comparing semantic meaning instead of exact terms, the system was able to retrieve relevant judgments even when there was little lexical overlap.

The baseline semantic retrieval achieved:

* Precision@1: **0.56**
* Precision@5: **0.76**
* Mean Reciprocal Rank (MRR): **0.653**
* Average Latency: **5605 ms**

Applying a Cross-Encoder reranker improved retrieval quality:

* Precision@1: **0.64**
* Precision@5: **0.84**
* Mean Reciprocal Rank (MRR): **0.733**
* Average Latency: **7084 ms**

The reranker successfully improved ranking accuracy but introduced additional computational cost, resulting in the highest query latency among all evaluated approaches.

### Weaknesses

Semantic retrieval occasionally ranked conceptually related judgments above the correct one, particularly when multiple cases discussed similar legal principles or involved comparable factual situations. While the reranker reduced some of these errors, it increased inference time significantly.

### Advantages

* Understands semantic meaning rather than relying solely on keywords.
* Performs well on paraphrased legal questions.
* Can retrieve relevant judgments even when exact legal terminology is absent.
* Reranking further improves the ordering of retrieved results.

### Limitations

* Slower than keyword search due to embedding retrieval and reranking.
* May retrieve semantically similar but incorrect judgments.
* Cross-Encoder reranking improves accuracy at the cost of noticeably higher latency.

## Hybrid Search

### Implementation

Hybrid retrieval combines keyword-based BM25 search with semantic vector search using Weaviate's hybrid retrieval mechanism. The contribution of each retrieval strategy is controlled through a configurable **alpha** parameter, allowing the balance between lexical matching and semantic similarity to be adjusted without modifying the retrieval pipeline.

This approach leverages the precision of keyword matching together with the flexibility of semantic embeddings, producing a single ranked result list.

### Strengths

Hybrid retrieval achieved the strongest overall performance across the evaluation dataset. It consistently benefited from both retrieval methods: keyword matching ensured that exact identifiers such as citations and case numbers were ranked highly, while semantic search improved retrieval for descriptive legal questions.

Evaluation results were:

* Precision@1: **0.76**
* Precision@5: **0.88**
* Mean Reciprocal Rank (MRR): **0.82**
* Average Latency: **5467 ms**

Compared with both keyword and semantic retrieval individually, hybrid search achieved the highest retrieval accuracy while maintaining moderate query latency.

### Weaknesses

Hybrid retrieval still inherits limitations from both underlying retrieval methods. In cases where both keyword and semantic retrieval rank incorrect but closely related judgments highly, the hybrid ranking may also fail to retrieve the expected judgment at the top position.

### Advantages

* Highest overall retrieval accuracy.
* Combines lexical precision with semantic understanding.
* Performs well across multiple query types.
* More robust than using either retrieval strategy independently.
* Configurable weighting allows future tuning without code changes.

### Limitations

* More computationally expensive than keyword search.
* Requires maintaining both the BM25 index and the vector database.
* Performance depends on selecting an appropriate hybrid weighting parameter.

**Query-Type Analysis**.



| Query Type                       | Example                                                                        | Best Strategy    | Why                                              |
| -------------------------------- | ------------------------------------------------------------------------------ | ---------------- | ------------------------------------------------ |
| Citation lookup                  | "Can you find the judgment reported as 2026 SHC 87?"                           | Keyword          | Exact citation matching                          |
| Case number lookup               | "Criminal Bail No. 1254/2017"                                                  | Keyword          | Structured identifier                            |
| Party names                      | "Marhaba Aviation Services vs Real Air Travel"                                 | Keyword          | Exact names                                      |
| Judge lookup                     | "Justice Aqeel Ahmed Abbasi"                                                   | Keyword / Hybrid | Metadata contains judge names                    |
| Statute lookup                   | "Article 199 of the Constitution"                                              | Hybrid           | Combines lexical and semantic relevance          |
| Natural-language legal questions | "Tell me about a case where security had to be furnished to release a vessel." | Hybrid           | Understands meaning while preserving legal terms |
| Admiralty fact patterns          | "Cargo shortage and arrest order"                                              | Hybrid           | Semantic similarity + keyword evidence           |

That naturally leads into the analysis.

---

# Query-Type Analysis

Different retrieval strategies perform best for different categories of legal queries. The evaluation set was designed to include a mixture of structured lookups, metadata searches, statutory references, and natural-language legal questions in order to evaluate each approach under realistic usage scenarios.

| Query Type                      | Example Query                                                                           | Best Performing Strategy | Reason                                                                                                         |
| ------------------------------- | --------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Citation Lookup                 | "Can you find the judgment reported as 2026 SHC 87?"                                    | Keyword Search           | Legal citations are structured identifiers that benefit from exact lexical matching.                           |
| Case Number Lookup              | "Why was a bail application withdrawn in Criminal Bail No. 1254/2017?"                  | Keyword Search           | Case numbers are unique identifiers and are retrieved most reliably using exact text matching.                 |
| Party Name Search               | "Find the case Marhaba Aviation Services vs Real Air Travel."                           | Keyword Search           | Exact party names produce highly accurate BM25 matches.                                                        |
| Judge Search                    | "Show me recent cases decided by Mr. Justice Aqeel Ahmed Abbasi."                       | Hybrid Search            | Combines exact metadata matching with semantic ranking of related judgments.                                   |
| Statutory Reference             | "Find cases on Article 199 of the Constitution."                                        | Hybrid Search            | Matches the statutory reference while retrieving semantically related judgments discussing the same provision. |
| Natural-Language Legal Question | "Tell me about a case where security had to be furnished to release a vessel or cargo." | Hybrid Search            | Captures the legal concept without requiring identical wording in the judgment.                                |
| Admiralty Case Description      | "What happened in the admiralty case involving a cargo shortage?"                       | Hybrid Search            | Combines lexical evidence ("cargo shortage") with semantic understanding of the surrounding legal context.     |

The evaluation demonstrates that no single retrieval strategy is optimal for every query type. Keyword retrieval performs exceptionally well for structured legal identifiers such as citations, case numbers, and party names because these queries rely on exact textual matches. Semantic retrieval improves performance on descriptive legal questions by identifying conceptually related judgments even when different wording is used.

Hybrid retrieval consistently provided the strongest overall performance by combining both approaches. It preserved the precision of keyword matching while improving recall for natural-language legal questions, resulting in the highest Precision@1 (0.76), Precision@5 (0.88), and Mean Reciprocal Rank (0.82) across the evaluation dataset. Based on these results, hybrid retrieval was selected as the default retrieval strategy for the final system.


# Cost and Latency Comparison

The retrieval strategies were compared not only in terms of retrieval quality but also computational cost and response latency. Since the system is deployed locally using Weaviate and Sentence Transformers, retrieval cost is primarily determined by processing time and computational complexity rather than external API charges.

| Retrieval Strategy   | Precision@1 | Precision@5 |      MRR | Average Latency | Computational Cost |
| -------------------- | ----------: | ----------: | -------: | --------------: | ------------------ |
| Keyword Search       |        0.72 |        0.84 |     0.78 |     **4444 ms** | Low                |
| Semantic Search      |        0.56 |        0.76 |    0.653 |         5605 ms | Medium             |
| Semantic + Reranking |        0.64 |        0.84 |    0.733 |     **7084 ms** | High               |
| Hybrid Search        |    **0.76** |    **0.88** | **0.82** |         5467 ms | Medium-High        |

Keyword retrieval incurred the lowest computational cost because it performs lexical matching without embedding similarity calculations or reranking. Consequently, it achieved the fastest average response time.

Semantic retrieval required vector similarity search over document embeddings, resulting in higher latency than keyword search. The addition of a Cross-Encoder reranker further increased computational cost because each candidate passage required an additional neural inference step before producing the final ranking.

Hybrid retrieval combined BM25 keyword search with vector similarity search. Although it required more computation than keyword retrieval alone, its latency remained substantially lower than semantic retrieval with reranking while achieving the highest overall retrieval accuracy. This represents the best balance between effectiveness and efficiency among the evaluated retrieval strategies.

Overall, the evaluation demonstrates that the modest increase in computational cost introduced by hybrid retrieval is justified by its consistent improvements in Precision@1, Precision@5, and Mean Reciprocal Rank.

# Recommendation

Based on the experimental evaluation, **hybrid retrieval** is recommended as the default retrieval strategy for the final Sindh High Court judgment retrieval system.

Among the evaluated approaches, hybrid retrieval achieved the strongest overall performance, with a **Precision@1 of 0.76**, **Precision@5 of 0.88**, and **Mean Reciprocal Rank (MRR) of 0.82**. Although its average latency (5467 ms) was slightly higher than keyword search, it remained significantly faster than semantic retrieval with Cross-Encoder reranking while consistently producing more accurate search results.

Keyword search remains highly effective for structured legal queries involving exact case numbers, citations, party names, and judge names. However, its reliance on lexical matching limits its ability to retrieve relevant judgments when users express legal concepts using different terminology.

Semantic retrieval improves the system's ability to understand natural-language legal questions and paraphrased queries. The additional Cross-Encoder reranking experiment further improved retrieval quality compared with baseline semantic search, but the increase in latency to approximately 7084 ms made it less suitable as the default retrieval strategy for interactive legal search.

Hybrid retrieval combines the complementary strengths of keyword and semantic retrieval. Exact lexical matching ensures reliable retrieval of structured legal identifiers, while semantic similarity enables effective handling of descriptive legal questions. The evaluation demonstrates that this combination provides the best balance between retrieval quality and response time across diverse legal query types.

The query classifier should remain the first stage of the retrieval pipeline. During evaluation, it achieved **100% classification accuracy**, correctly identifying all relevant legal questions while rejecting every off-domain query without false positives or false negatives. This prevents unnecessary retrieval operations for unrelated questions and ensures that the system remains focused on Sindh High Court judgments.

Based on these findings, the final system architecture adopts:

* **Query Classifier** for domain filtering.
* **Hybrid Retrieval** as the default retrieval strategy.
* **Structured metadata filtering** for precise legal document retrieval.
* **Semantic vector search** to improve handling of natural-language legal queries.

This configuration provides the strongest combination of retrieval accuracy, robustness, and computational efficiency among the evaluated approaches.

# Representative Retrieval Examples

The evaluation dataset contains a variety of legal query types, demonstrating that different retrieval strategies excel under different conditions.

| Query Type                      | Example Query                                                                           | Best Strategy            | Reason                                                                                                   |
| ------------------------------- | --------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------- |
| Exact Citation                  | *Can you find the judgment reported as 2026 SHC 87?*                                    | Keyword Search           | Exact legal citations are unique identifiers and are retrieved most accurately through lexical matching. |
| Case Number                     | *Why was a bail application withdrawn in Criminal Bail No. 1254/2017?*                  | Keyword Search           | Case numbers require exact text matching and benefit little from semantic similarity.                    |
| Party Names                     | *Find the case Marhaba Aviation Services vs Real Air Travel.*                           | Keyword Search           | Exact party names produce highly precise BM25 matches.                                                   |
| Judge Lookup                    | *Show me recent cases decided by Mr. Justice Aqeel Ahmed Abbasi.*                       | Hybrid Search            | Combines exact metadata matching with semantic ranking of related judgments.                             |
| Statutory Reference             | *Find cases on Article 199 of the Constitution.*                                        | Hybrid Search            | Retrieves judgments discussing the constitutional provision even when surrounding wording differs.       |
| Natural-Language Legal Question | *Tell me about a case where security had to be furnished to release a vessel or cargo.* | Semantic / Hybrid Search | Retrieves conceptually related judgments without requiring identical wording.                            |
| Admiralty Dispute               | *What happened in the admiralty case involving a cargo shortage?*                       | Hybrid Search            | Combines keyword evidence with semantic understanding of the underlying legal dispute.                   |

These examples illustrate that keyword retrieval is highly effective for structured legal identifiers, while semantic retrieval improves performance on descriptive legal questions. Hybrid retrieval consistently combines the strengths of both approaches, making it the most robust strategy across diverse legal search scenarios.




