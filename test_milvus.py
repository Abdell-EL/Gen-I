from pymilvus import MilvusClient

client = MilvusClient(uri="http://127.0.0.1:19530")

print("Connexion Milvus OK")

collections = client.list_collections()
print("Collections existantes :", collections)
