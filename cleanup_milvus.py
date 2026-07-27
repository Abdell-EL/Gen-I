from pymilvus import MilvusClient

client = MilvusClient(uri="http://127.0.0.1:19530")

collection_name = "test_documents"

if client.has_collection(collection_name=collection_name):
    client.drop_collection(collection_name=collection_name)
    print(f"Collection supprimée : {collection_name}")
else:
    print(f"Collection absente : {collection_name}")

