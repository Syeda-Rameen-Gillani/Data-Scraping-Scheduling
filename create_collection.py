import os

import weaviate
import weaviate.classes.config as wvc
from dotenv import load_dotenv
from weaviate_client import get_client

load_dotenv()

WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

client = get_client()

# Delete if it already exists (safe to re-run during dev)
if client.collections.exists(WEAVIATE_COLLECTION):
    client.collections.delete(WEAVIATE_COLLECTION)
    print(f"Deleted existing '{WEAVIATE_COLLECTION}' collection.")

client.collections.create(
    name=WEAVIATE_COLLECTION,
    properties=[
        wvc.Property(name="text", data_type=wvc.DataType.TEXT),
        wvc.Property(name="case_code", data_type=wvc.DataType.TEXT),
        wvc.Property(name="case_no", data_type=wvc.DataType.TEXT),
        wvc.Property(name="citation", data_type=wvc.DataType.TEXT),
        wvc.Property(name="topic", data_type=wvc.DataType.TEXT),
        wvc.Property(name="pdf_url", data_type=wvc.DataType.TEXT),
        wvc.Property(name="chunk_index", data_type=wvc.DataType.INT),
        wvc.Property(name="chunk_id", data_type=wvc.DataType.TEXT),
    ],
    vectorizer_config=wvc.Configure.Vectorizer.none(),
)

print("Created 'CaseChunk' collection.")
client.close()