from pymilvus import MilvusClient

COLLECTION_NAME = "test_documents"

client = MilvusClient(uri="http://127.0.0.1:19530")

print("Connexion Milvus OK")

# Nettoyage si la collection existe déjà
if client.has_collection(collection_name=COLLECTION_NAME):
    client.drop_collection(collection_name=COLLECTION_NAME)
    print(f"Collection supprimée : {COLLECTION_NAME}")

# Création d'une collection simple
client.create_collection(
    collection_name=COLLECTION_NAME,
    dimension=4,
    metric_type="COSINE",
)

print(f"Collection créée : {COLLECTION_NAME}")

# Données de test
data = [
    {
        "id": 1,
        "vector": [0.1, 0.2, 0.3, 0.4],
        "text": "Document sur Azure et les machines virtuelles"
    },
    {
        "id": 2,
        "vector": [0.2, 0.1, 0.4, 0.3],
        "text": "Document sur Milvus et les bases vectorielles"
    },
    {
        "id": 3,
        "vector": [0.9, 0.8, 0.7, 0.6],
        "text": "Document sur cuisine et recettes"
    },
]

client.insert(
    collection_name=COLLECTION_NAME,
    data=data
)

print("Données insérées")

# Recherche vectorielle
results = client.search(
    collection_name=COLLECTION_NAME,
    data=[[0.2, 0.1, 0.4, 0.3]],
    limit=2,
    output_fields=["text"]
)

print("Résultat recherche :")
for hit in results[0]:
    print(hit)

