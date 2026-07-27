import os
from functools import lru_cache
from typing import Any

from pymilvus import Collection, connections
from sentence_transformers import SentenceTransformer


MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "sogetrel_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_collection() -> Collection:
    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
    collection = Collection(MILVUS_COLLECTION)
    collection.load()
    return collection


def build_query_embedding_text(query: str) -> str:
    return (
        "Domaine: FDE\n"
        "Type de recherche: question utilisateur\n"
        "Objectif: retrouver les procédures, règles métier, codes situation et cas applicables.\n"
        f"Question:\n{query}"
    )


def embed_query(query: str) -> list[float]:
    model = get_embedding_model()
    embedding_text = build_query_embedding_text(query)

    vector = model.encode(
        embedding_text,
        normalize_embeddings=True,
    )

    return [float(x) for x in vector]


def search_chunks(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    query_vector = embed_query(query)
    collection = get_collection()

    results = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {}},
        limit=top_k,
        output_fields=[
            "id",
            "text",
            "kb_code",
            "article_title",
            "section_title",
            "chunk_type",
            "priority",
            "metadata",
        ],
    )

    hits = []

    for rank, hit in enumerate(results[0], start=1):
        entity = hit.entity

        hits.append(
            {
                "rank": rank,
                "score": float(hit.distance),
                "id": entity.get("id"),
                "text": entity.get("text"),
                "kb_code": entity.get("kb_code"),
                "article_title": entity.get("article_title"),
                "section_title": entity.get("section_title"),
                "chunk_type": entity.get("chunk_type"),
                "priority": entity.get("priority"),
                "metadata": entity.get("metadata"),
            }
        )

    return hits