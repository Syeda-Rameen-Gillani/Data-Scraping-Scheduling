from weaviate_client import get_client
from weaviate.classes.query import Filter

client = get_client()
collection = client.collections.get("CaseChunk")

response = collection.query.fetch_objects(
    filters=Filter.by_property("text").like("*TEST EDIT*"),
    limit=10,
)
for obj in response.objects:
    print(obj.uuid, "|", obj.properties.get("case_code"), "|", obj.properties.get("chunk_id"))

client.close()
