import weaviate

client = weaviate.connect_to_local()
collection = client.collections.get("CaseChunk")

response = collection.query.fetch_objects(limit=5)
for obj in response.objects:
    print("case_no:", obj.properties.get("case_no"))
    print("citation:", obj.properties.get("citation"))
    print("---")

client.close()