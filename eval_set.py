"""
eval_set.py

Self-authored evaluation set for Stage 3 (Advanced Retrieval & Evaluation).

- Questions 1-10 are grounded in the actual text of 10 real Sindh High
  Court judgments ingested into Weaviate. Every expected fact was verified
  directly against the source PDF (not just the LLM-extracted metadata,
  which was found to contain several numeric errors during verification
  -- see DECISIONS.md).
- Questions 11-15 are off-domain/irrelevant queries used to evaluate the
  query classifier (Stage 3, Task 3). They have no expected_file_name
  because they should not retrieve anything relevant at all.
"""

EVAL_SET = [
    {
        "question": "What was decided about the cargo aboard the M.V. Miski bound for the Port of Sudan?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Cargo released to plaintiff (Hays Trading & Shipping) conditional on alternate vessel, US$60,000 security, KPT dues paid.",
    },
    {
        "question": "Marhaba Aviation Services sued over dishonored cheques - what was claimed versus what was actually decreed?",
        "expected_file_name": "Sindh High Court - MTE0ODk4Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Claimed: Rs. 222,009,539 outstanding. Decreed: Rs. 115,000,000 (LLM metadata wrongly implied the full claimed amount was decreed).",
    },
    {
        "question": "A woman was released from prison after serving how much of a 5-year sentence?",
        "expected_file_name": "Sindh High Court - MTY1OTBjZm1zLWRjODM=",
        "expected_label": "relevant",
        "notes": "16 months. Verified accurate in metadata.",
    },
    {
        "question": "What amount was sought for short-landed cargo, and under which law?",
        "expected_file_name": "Sindh High Court - MTU5OTc0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "US $114,125 (metadata wrongly said '$1.14 million' -- misread Pakistani-style digit grouping 1,14,125). Admiralty Jurisdiction of the High Court Ordinance, 1980.",
    },
    {
        "question": "Why was a bail application withdrawn in Criminal Bail No. 1254/2017?",
        "expected_file_name": "Sindh High Court - MTIwOTU3Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Accused had already been acquitted by the trial court. Verified accurate in metadata.",
    },
    {
        "question": "In the compromise decree case dismissed against Defendants No. 4 and 5, who represented the Plaintiff?",
        "expected_file_name": "Sindh High Court - MjI3ODA3Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Mr. Muhammad Mansoor Mir, Advocate (metadata mislabeled him as the petitioner/party rather than counsel).",
    },
    {
        "question": "Who pleaded urgency on an execution matter in IInd Appeal No. 68/2013?",
        "expected_file_name": "Sindh High Court - MTAwNjYxY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Mr. Muhammad Rasheed, Advocate. Note: this question contains a case-number pattern (68/2013), so it will trigger the exact case-number lookup path, not semantic vector search.",
    },
    {
        "question": "What is the case number for the M.V. Miski cargo-release dispute?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Adm. Suit 2/2018.",
    },
    {
        "question": "What security amount had to be furnished before the M.V. Miski cargo could be released?",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "US$60,000 or equivalent in Pak Rupees.",
    },
    {
        "question": "In the 2009 compromise case, how much did defendant No. 2 deposit for the ship's release, and how much did the Nazir separately hold in rupees?",
        "expected_file_name": "Sindh High Court - MTIwMTE2Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "US $300,000 for ship release; Nazir separately held Rs. 24,030,000 (metadata wrongly said '$240,330,000' -- same digit-grouping misread as Q4).",
    },
    {
        "question": "What's the capital of France?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "notes": "General knowledge, unrelated to Pakistani case law.",
    },
    {
        "question": "Can you recommend a good biryani recipe?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "notes": "Completely off-domain.",
    },
    {
        "question": "How do I reset my email password?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "notes": "Completely off-domain.",
    },
    {
        "question": "What are the requirements for filing a divorce in California?",
        "expected_file_name": None,
        "expected_label": "irrelevant",
        "notes": "Legal, but wrong jurisdiction and not in this corpus.",
    },
    {
        "question": "Summarize a recent Lahore High Court inheritance ruling.",
        "expected_file_name": None,
        "expected_label": "irrelevant",
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
        "notes": "Ambiguous by design: MTI0NjQwY2Ztcy1kYzgz and MTU5OTc0Y2Ztcy1kYzgz also mention the Nazir (as security-holder), but MTIwMTE2Y2Ztcy1kYzgz is the case actually ABOUT money paid to the Nazir and released by him.",
    },
    {
        "question": "Tell me about a case where security had to be furnished to release a vessel or cargo.",
        "expected_file_name": "Sindh High Court - MTI0NjQwY2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Ambiguous by design: MTU5OTc0Y2Ztcy1kYzgz also involves furnishing security to a vessel, but MTI0NjQwY2Ztcy1kYzgz is the more central 'security for release' case (M.V. Miski).",
    },
    {
        "question": "What happened in the admiralty case involving a cargo shortage?",
        "expected_file_name": "Sindh High Court - MTU5OTc0Y2Ztcy1kYzgz",
        "expected_label": "relevant",
        "notes": "Ambiguous by design: MTI0NjQwY2Ztcy1kYzgz is also an admiralty/cargo case, but MTU5OTc0Y2Ztcy1kYzgz is specifically about short-landed cargo (a shortage), not a release dispute.",
    },
]