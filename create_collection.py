import os

import weaviate
import weaviate.classes.config as wvc
from dotenv import load_dotenv
from weaviate_client import get_client

load_dotenv()

WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

client = get_client()

# Delete if it already exists (safe to re-run during dev).
# NOTE: this is destructive — recreating the collection wipes all
# previously-ingested chunks. That's expected as part of the Phase 1
# migration (enrich JSONs -> recreate collection -> re-ingest from
# scratch), but don't run this against a collection you want to keep.
if client.collections.exists(WEAVIATE_COLLECTION):
    client.collections.delete(WEAVIATE_COLLECTION)
    print(f"Deleted existing '{WEAVIATE_COLLECTION}' collection.")

client.collections.create(
    name=WEAVIATE_COLLECTION,
    properties=[
        # -- chunk-level fields --
        wvc.Property(name="text", data_type=wvc.DataType.TEXT),
        wvc.Property(name="chunk_index", data_type=wvc.DataType.INT),
        wvc.Property(name="chunk_id", data_type=wvc.DataType.TEXT),

        # -- identity / court fields --
        wvc.Property(name="file_name", data_type=wvc.DataType.TEXT),
        wvc.Property(name="page_count", data_type=wvc.DataType.INT),
        wvc.Property(name="court_name", data_type=wvc.DataType.TEXT),
        wvc.Property(name="court_type", data_type=wvc.DataType.TEXT),
        wvc.Property(name="case_title", data_type=wvc.DataType.TEXT),
        wvc.Property(name="case_number", data_type=wvc.DataType.TEXT),

        # -- petition / disposition --
        wvc.Property(name="type_of_petition", data_type=wvc.DataType.TEXT),
        wvc.Property(name="case_category", data_type=wvc.DataType.TEXT),
        wvc.Property(name="disposition_type", data_type=wvc.DataType.TEXT),
        wvc.Property(name="bench_strength", data_type=wvc.DataType.INT),

        # -- citation fields --
        # citation_page_number is TEXT, not INT: resolve_citation_fields()
        # in metadata_enrichment.py keeps it as the raw regex capture
        # group (a string), e.g. "87" not 87.
        wvc.Property(name="citation_year", data_type=wvc.DataType.INT),
        wvc.Property(name="citation_journal", data_type=wvc.DataType.TEXT),
        wvc.Property(name="citation_page_number", data_type=wvc.DataType.TEXT),

        # -- dates --
        # Stored as TEXT ("YYYY-MM-DD" strings from the LLM prompt), NOT
        # Weaviate's native DATE type. DATE requires full RFC3339
        # datetimes (e.g. "2023-08-07T00:00:00Z"); metadata_enrichment.py
        # only produces plain date strings, so inserting them as DATE
        # would error. If you want native date range filtering later,
        # convert to RFC3339 at ingestion time and switch these to
        # wvc.DataType.DATE — for now TEXT keeps ingestion simple and
        # matches what the LLM actually returns.
        wvc.Property(name="case_filing_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="trial_court_decision_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="appellate_court_decision_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="high_court_decision_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="supreme_court_decision_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="hearing_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="decision_order_date", data_type=wvc.DataType.TEXT),

        # -- parties / representation --
        wvc.Property(name="petitioner_appellant", data_type=wvc.DataType.TEXT),
        wvc.Property(name="respondent", data_type=wvc.DataType.TEXT),
        wvc.Property(name="applicant_and_respondents", data_type=wvc.DataType.TEXT),
        wvc.Property(name="advocate_names", data_type=wvc.DataType.TEXT),
        wvc.Property(name="judge_names", data_type=wvc.DataType.TEXT),

        # -- legal substance --
        wvc.Property(name="fir_number_and_date", data_type=wvc.DataType.TEXT),
        wvc.Property(name="legal_sections_involved", data_type=wvc.DataType.TEXT),
        wvc.Property(name="articles_sections_cited", data_type=wvc.DataType.TEXT_ARRAY),
        wvc.Property(name="statutes_mentioned", data_type=wvc.DataType.TEXT_ARRAY),
        wvc.Property(name="key_legal_issues", data_type=wvc.DataType.TEXT_ARRAY),
        wvc.Property(name="head_note", data_type=wvc.DataType.TEXT),
        wvc.Property(name="cited_case_laws", data_type=wvc.DataType.TEXT),
        wvc.Property(name="precedents_cited", data_type=wvc.DataType.TEXT_ARRAY),
        wvc.Property(name="short_summary", data_type=wvc.DataType.TEXT),
        wvc.Property(name="legal_keywords", data_type=wvc.DataType.TEXT_ARRAY),
        wvc.Property(name="final_decision", data_type=wvc.DataType.TEXT),

        # -- source tracking --
        wvc.Property(name="reference_url", data_type=wvc.DataType.TEXT),
        wvc.Property(name="source_url", data_type=wvc.DataType.TEXT),
    ],
    vectorizer_config=wvc.Configure.Vectorizer.none(),
)

print(f"Created '{WEAVIATE_COLLECTION}' collection.")
client.close()