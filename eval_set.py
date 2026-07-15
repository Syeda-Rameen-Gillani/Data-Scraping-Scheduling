"""
eval_set.py

Self-authored evaluation set for Stage 3/4 (Advanced Retrieval & Evaluation).

Every entry now has a "query_type" field tagging which of the Stage 4
brief's 7 required query shapes it exercises: exact_citation,
case_file_number, judge_reference, case_title_party_name,
natural_language_legal_problem, statute_section_reference, or irrelevant.

Many entries also have a "predicted_advantage" field: "keyword", "semantic",
"hybrid", or "all_fail". These are HYPOTHESES about which retrieval
strategy should win on that question, based on the shape of the query and
the corpus (see reasoning in each entry's notes) -- they are NOT confirmed
results. Confirming them requires actually running evaluate.py and checking
which strategy's per-question rank each one gets; see DECISIONS.md /
evaluation_results/ for the real numbers once that's done.

--- Verification status, please read before trusting a question ---

Questions 1-10 (original Stage 3 set) are grounded in the actual text of
10 real Sindh High Court judgments ingested into Weaviate. Every expected
fact was verified directly against the SOURCE PDF (not just the
LLM-extracted metadata, which was found to contain several numeric errors
during verification -- see DECISIONS.md).

Questions 11-15 are off-domain/irrelevant queries used to evaluate the
query classifier. They have no expected_file_name because they should not
retrieve anything relevant at all.

Questions 16-18 are the original deliberately-ambiguous set (added to
break a ceiling effect -- see the comment above them).

Questions 19 onward (added when the eval set was expanded to cover all 7
query types + keyword/semantic/hybrid comparison examples) are grounded
in the 50-record metadata JSON export, cross-checked against the
"final_decision" / "petitioner_appellant" / "respondent" / "Judge Name(s)"
fields shown in that export. They are NOT independently re-verified
against the source PDFs the way questions 1-10 were -- the metadata JSON
itself is the LLM's extraction, which DECISIONS.md already documents as
containing occasional errors (e.g. the digit-grouping misreads in Q2/Q4/Q10).
Treat facts in questions 19+ as "as good as the metadata," not as
PDF-verified ground truth.

--- Corpus limitations discovered while building questions 19+ ---

1. EXACT CITATION IS CURRENTLY UNTESTABLE: all 50 real metadata records
   have citation_year / citation_journal / citation_page_number = None.
   Not one judgment in the corpus has a populated "YYYY SHC NNN"-style
   citation. This isn't a retrieval bug -- resolve_citation_fields() in
   metadata_enrichment.py falls back to the case file number specifically
   because none of these judgments' listing pages had a parseable citation
   yet. Question 19 below documents the intended query type for classifier
   testing purposes (expected_label="relevant") but deliberately has
   expected_file_name=None since there is no real judgment to retrieve --
   evaluate.py's own filter (only scores questions with a truthy
   expected_file_name) already excludes it from retrieval hit-rate/MRR
   automatically, so this doesn't skew those numbers.

2. CASE TITLE / PARTY NAME HAS A REAL ROUTING GAP, NOT JUST A DATA GAP:
   "Case Title" is None or LLM placeholder junk ("Admiralty",
   "Sindh Chief Court Rules") in every one of the 50 records -- so
   lookup_by_case_title() will never find anything against this corpus.
   Meanwhile petitioner_appellant/respondent ARE populated with real party
   names. The problem: detect_party_name() in retrieval.py explicitly
   returns False whenever detect_case_title() matches (i.e. whenever the
   query contains "vs"/"v."/"versus"), so for a brief-style query like
   "X vs Y", lookup_by_party() never even gets tried as a fallback --
   the query goes straight from a doomed case_title lookup to semantic
   search, skipping the one structured lookup that could have actually
   worked. Question 22 below exercises this path and documents the gap;
   fixing it would mean also trying lookup_by_party() within the
   case_title branch of _structured_lookup(), not just case_title.
"""

EVAL_SET = [
    {
        "question": "What was decided about the cargo aboard the M.V. Miski bound for the Port of Sudan?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Cargo released to plaintiff (Hays Trading & Shipping) conditional on alternate vessel, US$60,000 security, KPT dues paid.",
    },
    {
        "question": "Marhaba Aviation Services sued over dishonored cheques - what was claimed versus what was actually decreed?",
        "expected_file_name": "Sindh High Court - MTE0ODk4Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Claimed: Rs. 222,009,539 outstanding. Decreed: Rs. 115,000,000 (LLM metadata wrongly implied the full claimed amount was decreed).",
    },
    {
        "question": "A woman was released from prison after serving how much of a 5-year sentence?",
        "expected_file_name": "Sindh High Court - MTY1OTBjZm1zLWRjODM=",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "16 months. Verified accurate in metadata.",
    },
    {
        "question": "What amount was sought for short-landed cargo, and under which law?",
        "expected_file_name": "Sindh High Court - MTU5OTc0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "US $114,125 (metadata wrongly said '$1.14 million' -- misread Pakistani-style digit grouping 1,14,125). Admiralty Jurisdiction of the High Court Ordinance, 1980.",
    },
    {
        "question": "Why was a bail application withdrawn in Criminal Bail No. 1254/2017?",
        "expected_file_name": "Sindh High Court - MTIwOTU3Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "case_file_number",
        "notes": "Accused had already been acquitted by the trial court. Verified accurate in metadata. Contains a case-number pattern (1254/2017), triggers exact lookup.",
    },
    {
        "question": "In the compromise decree case dismissed against Defendants No. 4 and 5, who represented the Plaintiff?",
        "expected_file_name": "Sindh High Court - MjI3ODA3Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Mr. Muhammad Mansoor Mir, Advocate (metadata mislabeled him as the petitioner/party rather than counsel).",
    },
    {
        "question": "Who pleaded urgency on an execution matter in IInd Appeal No. 68/2013?",
        "expected_file_name": "Sindh High Court - MTAwNjYxY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "case_file_number",
        "notes": "Mr. Muhammad Rasheed, Advocate. Contains a case-number pattern (68/2013), triggers the exact case-number lookup path, not semantic vector search.",
    },
    {
        "question": "What is the case number for the M.V. Miski cargo-release dispute?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Adm. Suit 2/2018. Question asks FOR a case number rather than containing one, so it doesn't itself trigger the case-number lookup path.",
    },
    {
        "question": "What security amount had to be furnished before the M.V. Miski cargo could be released?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "US$60,000 or equivalent in Pak Rupees.",
    },
    {
        "question": "In the 2009 compromise case, how much did defendant No. 2 deposit for the ship's release, and how much did the Nazir separately hold in rupees?",
        "expected_file_name": "Sindh High Court - MTIwMTE2Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "US $300,000 for ship release; Nazir separately held Rs. 24,030,000 (metadata wrongly said '$240,330,000' -- same digit-grouping misread as Q4).",
    },
    {
        "question": "What's the capital of France?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "query_type": "irrelevant",
        "notes": "General knowledge, unrelated to Pakistani case law.",
    },
    {
        "question": "Can you recommend a good biryani recipe?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "query_type": "irrelevant",
        "notes": "Completely off-domain.",
    },
    {
        "question": "How do I reset my email password?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "query_type": "irrelevant",
        "notes": "Completely off-domain.",
    },
    {
        "question": "What are the requirements for filing a divorce in California?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "query_type": "irrelevant",
        "notes": "Legal, but wrong jurisdiction and not in this corpus.",
    },
    {
        "question": "Summarize a recent Lahore High Court inheritance ruling.",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "query_type": "irrelevant",
        "notes": "Legal and Pakistani, but wrong court -- not covered by this Sindh High Court corpus.",
    },

    # --- Deliberately ambiguous questions -----------------------------------
    # Baseline (Q1-10) hit 100% Hit Rate / MRR 1.0 -- a ceiling effect from
    # only having 10 documents, most on distinct topics. These questions
    # target three judgments that share overlapping vocabulary (cargo,
    # vessel, security, money deposited with the court's "Nazir"), so vector
    # search has real candidates to choose between. This gives reranking and
    # hybrid search room to actually demonstrate a difference.
    {
        "question": "What case involved money being paid to the Nazir of the court?",
        "expected_file_name": "Sindh High Court - MTIwMTE2Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Ambiguous by design: MTI0NjQwY2Ztcy1kYzgz and MTU5OTc0Y2Ztcy1kYzgz also mention the Nazir (as security-holder), but MTIwMTE2Y2Ztcy1kYzgz is the case actually ABOUT money paid to the Nazir and released by him.",
    },
    {
        "question": "Tell me about a case where security had to be furnished to release a vessel or cargo.",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "notes": "Ambiguous by design: MTU5OTc0Y2Ztcy1kYzgz also involves furnishing security to a vessel, but MTI0NjQwY2Ztcy1kYzgz is the more central 'security for release' case (M.V. Miski).",
    },
    {
        "question": "What happened in the admiralty case involving a cargo shortage?",
        "expected_file_name": "Sindh High Court - MTU5OTc0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "all_fail",
        "notes": "Ambiguous by design: MTI0NjQwY2Ztcy1kYzgz is also an admiralty/cargo case, but MTU5OTc0Y2Ztcy1kYzgz is specifically about short-landed cargo (a shortage), not a release dispute. CONFIRMED (not just predicted) all-three-fail case: evaluation_results/eval_20260708_155949.json shows baseline, reranked, AND hybrid all instead return MTU5OTc2Y2Ztcy1kYzgz -- a different, near-consecutive case ID (159976 vs expected 159974) from the same filing batch. See DECISIONS.md Section 7 for the full writeup.",
    },

    # --- Query type: exact_citation ------------------------------------
    {
        "question": "Can you find the judgment reported as 2026 SHC 87?",
        "expected_file_name": None,
        "expected_label": "relevant",
        "query_type": "exact_citation",
        "notes": "UNTESTABLE FOR RETRIEVAL against the current corpus: all 50 real metadata records have citation_year/citation_journal/citation_page_number = None -- not one judgment has a populated citation yet. expected_file_name is deliberately None so evaluate.py's own filter excludes this from Hit Rate/MRR scoring (it only scores questions with a truthy expected_file_name). expected_label='relevant' is still correct and meaningful for CLASSIFIER evaluation -- a citation-format question is a legitimate legal query in principle, even though this corpus can't currently satisfy it. See module docstring, limitation #1.",
    },

    # --- Query type: judge_reference ------------------------------------
    {
        "question": "Show me recent cases decided by Mr. Justice Aqeel Ahmed Abbasi.",
        "expected_file_name": "Sindh High Court - MTU5OTczY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "judge_reference",
        "notes": "Judge Name(s) field: 'Mr. Justice Aqeel Ahmed Abbasi; Mr. Justice Muhammad Junaid Ghaffar' -- the ONLY record in the 50-record export whose judge field contains the literal word 'Justice' (JUDGE_PATTERN in retrieval.py requires it). Most other records store judge names without the 'Justice' title (e.g. 'Muhammad Ali Mazhar, J', 'ARSHAD', 'Asif'), so this detector is currently narrow -- see the earlier retrieval.py review.",
    },

    # --- Query type: statute_section_reference ---------------------------
    {
        "question": "Find cases on Article 199 of the Constitution.",
        "expected_file_name": "Sindh High Court - MTA3OTQyY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "statute_section_reference",
        "notes": "articles_sections_cited includes 'Article 199' -- the only record in the export citing it, so this should be an unambiguous exact match via lookup_by_article().",
    },

    # --- Query type: case_title_party_name --------------------------------
    {
        "question": "Find the case Marhaba Aviation Services vs Real Air Travel.",
        "expected_file_name": "Sindh High Court - MTE0ODk4Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "case_title_party_name",
        "notes": "Same underlying judgment as Q2 (dishonored cheques case), deliberately reused with 'X vs Y' phrasing to specifically exercise the case_title/party-name routing path rather than the natural-language path Q2 already covers. EXPECTED TO CURRENTLY FAIL THE STRUCTURED LOOKUP AND FALL BACK TO SEMANTIC/HYBRID SEARCH: Case Title is unpopulated garbage for every record in this corpus, so lookup_by_case_title() will find nothing, and detect_party_name() (which WOULD succeed via the populated petitioner_appellant/respondent fields) is never tried because detect_case_title() matching a 'vs' query short-circuits it first. See module docstring, limitation #2. This is a real routing gap worth fixing, not a data problem.",
    },

    # --- Predicted keyword-wins candidates ---------------------------------
    # Hypothesis: these contain a rare/distinctive proper noun or exact
    # figure that BM25 can match verbatim, while the surrounding admiralty
    # boilerplate vocabulary (vessel, arrest, security, cargo) is shared
    # across many corpus documents -- exactly the kind of overlap that
    # confused vector search on the Nazir/security/cargo-shortage triad
    # above. UNCONFIRMED: run evaluate.py with the keyword strategy and
    # check the per-question rank to verify these actually win.
    {
        "question": "What happened with the vessel M.V. NAVIOS VENUS regarding a cargo shortage and arrest order?",
        "expected_file_name": "Sindh High Court - MTU5OTY1Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "keyword",
        "notes": "PREDICTED, not confirmed. 'NAVIOS VENUS' is a rare, distinctive vessel name likely unique in the corpus -- BM25 should match it exactly, while a bi-encoder may not weight an unusual foreign proper noun as strongly as the shared surrounding admiralty vocabulary (cargo, arrest, security) that overlaps with several other vessel-arrest judgments.",
    },
    {
        "question": "What happened in the case involving the vessel M.V. Yasa Aysen and a time charter dispute with Global Bulk International FZE?",
        "expected_file_name": "Sindh High Court - MTM5ODc0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "keyword",
        "notes": "PREDICTED, not confirmed. 'Yasa Aysen' and 'Global Bulk International FZE' are rare, distinctive proper nouns -- same reasoning as the NAVIOS VENUS example.",
    },
    {
        "question": "Which admiralty case was partly decreed for US Dollars-120,710.6 involving an unseaworthy vessel and dishonored cheques?",
        "expected_file_name": "Sindh High Court - MTQwNTY1Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "keyword",
        "notes": "PREDICTED, not confirmed. The exact monetary figure 'US Dollars-120,710.6' is a highly specific token BM25 can match verbatim; sentence-embedding models generally handle exact numeric strings much less reliably than exact keyword matching does. Note this judgment is ALSO part of the M.V. Miski cluster (respondent 'MV Miski and others'), but the query doesn't need to say 'Miski' -- the dollar figure and 'unseaworthy'/'dishonored cheques' combination should be distinctive enough on their own.",
    },

    # --- Predicted semantic-wins candidates --------------------------------
    # Hypothesis: these are paraphrases that deliberately AVOID the exact
    # terminology/vocabulary the source judgment uses, so BM25 has little to
    # latch onto -- only a model that captures meaning rather than exact
    # wording should surface the right document. UNCONFIRMED.
    {
        "question": "A woman was granted early release from custody, having completed only a fraction of her original prison term -- what were the circumstances?",
        "expected_file_name": "Sindh High Court - MTY1OTBjZm1zLWRjODM=",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "semantic",
        "notes": "PREDICTED, not confirmed. Paraphrase of Q3's fact avoiding the exact terms 'remission'/'16 months'/'5-year sentence' that the source text and metadata actually use -- deliberately relies on meaning ('early release', 'fraction of her original term') rather than matching wording.",
    },
    {
        "question": "Why did a shipping company's lawsuit get dismissed over a dispute about who had the proper authority to file it on the company's behalf?",
        "expected_file_name": "Sindh High Court - MTM4ODczY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "semantic",
        "notes": "PREDICTED, not confirmed. Deliberately does NOT name the plaintiff company ('JUGOLINIJA') or cite 'Order XXIX Rule 1 CPC'/'Board Resolution' -- if this correctly surfaces the JUGOLINIJA case anyway, it's because the model understood the underlying legal concept (authority to sue on a company's behalf), not because it matched any distinctive token.",
    },
    {
        "question": "Which admiralty case ended when the two sides worked out a private deal, causing the vessel's arrest to be lifted?",
        "expected_file_name": "Sindh High Court - MTIwOTg0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "semantic",
        "notes": "PREDICTED, not confirmed. Avoids the source metadata's actual terms 'dismissed as withdrawn'/'amicable resolution'/'arrest orders...recalled', substituting 'worked out a private deal' and 'arrest...lifted' instead. Risk: several other records in this corpus ALSO involve withdrawn admiralty suits with recalled arrest orders (e.g. MjI3ODM5Y2Ztcy1kYzgz, MjI3ODY5Y2Ztcy1kYzgz, MjI3OTI0Y2Ztcy1kYzgz all show 'Dismissed as withdrawn' + arrest-related keywords) -- this may turn out to be genuinely ambiguous rather than a clean semantic win. Worth checking the actual rank carefully, not just hit/miss.",
    },

    # --- Predicted hybrid-wins candidates -----------------------------------
    # Hypothesis: the M.V. Miski name appears across at least 6 different
    # admiralty suits in this corpus (MTI0NjQwY2Ztcy1kYzgz, MTI0NzM2Y2Ztcy1kYzgz,
    # MTQwMTQyY2Ztcy1kYzgz, MTQwNTY0Y2Ztcy1kYzgz, MTQwNTY1Y2Ztcy1kYzgz,
    # MTQxMjgzY2Ztcy1kYzgz) -- a real-world version of the same
    # overlapping-vocabulary problem the Nazir/security/cargo-shortage
    # triad tests, but at larger scale. A pure keyword search on "M.V.
    # Miski" alone can't disambiguate between six documents that all
    # contain it; pure semantic search may also blur them since they share
    # heavy admiralty vocabulary. The hypothesis is that BM25 keying on
    # the specific distinguishing terms PLUS vector similarity on the
    # overall topic together should outperform either alone. UNCONFIRMED --
    # this is exactly the kind of claim that needs an actual evaluate.py
    # run and per-question rank comparison before it goes in the
    # comparison document as fact.
    {
        "question": "Which M.V. Miski case involved seafarers claiming unpaid crew wages and repatriation expenses?",
        "expected_file_name": "Sindh High Court - MTQwMTQyY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "hybrid",
        "notes": "PREDICTED, not confirmed. Plaintiffs: Fareed Ahmed Khan and 12 others; Merchant Shipping Ordinance 2001; repatriation expenses.",
    },
    {
        "question": "Which M.V. Miski case awarded the plaintiff $860,500 for damage and breach of contract, represented by Mr. Abdul Razzaq, Advocate?",
        "expected_file_name": "Sindh High Court - MTQxMjgzY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "hybrid",
        "notes": "PREDICTED, not confirmed. Plaintiff: Hays Trading & Shipping (a DIFFERENT Hays Trading & Shipping suit than Q1/Q8/Q9's target -- same recurring plaintiff, different M.V. Miski suit, different advocate and amount).",
    },
    {
        "question": "Which M.V. Miski case involved a Gulf bank enforcing a foreign court's judgment to recover a loan?",
        "expected_file_name": "Sindh High Court - MTQwNTY0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "query_type": "natural_language_legal_problem",
        "predicted_advantage": "hybrid",
        "notes": "PREDICTED, not confirmed. Plaintiff: M/s. Commercial Bank International PSC; Sharjah Federal Court judgment for AED 5,723,557.",
    },
]