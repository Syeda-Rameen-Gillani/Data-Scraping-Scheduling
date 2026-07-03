"""
Diagnostic script: bypasses the LLM entirely and prints exactly what
/chat would retrieve from Weaviate for a given query. Run this to check
whether a bad answer is a retrieval problem or a generation problem.

Usage:
    python debug_retrieval.py "What happened in Adm. Suit 1/2019 (S.B.) Sindh High Court, Karachi?"
"""
import sys
import re
from weaviate.classes.query import Filter
from weaviate_client import get_client
from sentence_transformers import SentenceTransformer

TOP_K = 5

if len(sys.argv) < 2:
    print("Usage: python debug_retrieval.py \"your question here\"")
    sys.exit(1)

q = sys.argv[1]
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

client = get_client()
collection = client.collections.get("CaseChunk")

case_match = re.search(r"\d+/\d{4}", q)

if case_match:
    case_id = case_match.group()
    print(f"[exact-match branch] case_id detected: {case_id}\n")
    results = collection.query.fetch_objects(
        filters=Filter.by_property("case_no").like(f"*{case_id}*")
    )
else:
    print("[semantic branch]\n")
    query_vector = embed_model.encode(q).tolist()
    results = collection.query.near_vector(near_vector=query_vector, limit=TOP_K)

print(f"Total objects returned: {len(results.objects)}\n")

seen_texts = set()
for i, obj in enumerate(results.objects, start=1):
    props = obj.properties
    text = props.get("text", "")
    is_dup = text in seen_texts
    seen_texts.add(text)
    print(f"--- object {i} | case_code={props.get('case_code')} | chunk_index={props.get('chunk_index')} | DUPLICATE TEXT: {is_dup} ---")
    print(text[:300])
    print()

print(f"\nUnique chunk texts among {len(results.objects)} results: {len(seen_texts)}")
print(f"Unique case_codes among results: {len(set(o.properties.get('case_code') for o in results.objects))}")

client.close()