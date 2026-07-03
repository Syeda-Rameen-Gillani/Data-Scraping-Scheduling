import weaviate

def get_client():
    return weaviate.connect_to_local()