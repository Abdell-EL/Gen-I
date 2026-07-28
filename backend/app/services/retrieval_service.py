import os
from functools import lru_cache
import time
from typing import Any

from pymilvus import Collection, connections
from sentence_transformers import SentenceTransformer

from app.config import get_cache_settings
from app.services.cache_service import (
    acquire_lock,
    bounded_wait_for_json,
    delete_key,
    embedding_cache_key,
    get_knowledge_generation,
    read_json,
    release_lock,
    retrieval_cache_key,
    validate_embedding,
    validate_retrieval_payload,
    write_json,
)


MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "sogetrel_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
SEMANTIC_RETRIEVAL_CONFIG = {
    "anns_field": "embedding",
    "metric_type": "COSINE",
    "params": {},
    "ranking": "distance_descending",
}


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


def _encode_query(model: SentenceTransformer, query: str) -> list[float]:
    vector = model.encode(
        build_query_embedding_text(query),
        normalize_embeddings=True,
    )
    return [float(value) for value in vector]


def embed_query(query: str, performance: dict[str, Any] | None = None) -> list[float]:
    started = time.perf_counter()
    settings = get_cache_settings()
    model = get_embedding_model()
    dimension = int(model.get_sentence_embedding_dimension() or 0)
    key = embedding_cache_key(settings, EMBEDDING_MODEL, query)
    cached = read_json(key, settings)
    if performance is not None:
        performance["cache_lookup_ms"] = performance.get("cache_lookup_ms", 0.0) + cached.lookup_ms
        performance["embedding_cache_status"] = cached.status
    vector = validate_embedding(cached.value, dimension)
    if vector is not None:
        if performance is not None:
            performance["embedding_ms"] = (time.perf_counter() - started) * 1000
        return vector
    if cached.value is not None:
        delete_key(key, settings)

    token = acquire_lock(key, settings=settings)
    if token is not None:
        double_checked = read_json(key, settings)
        if performance is not None:
            performance["cache_lookup_ms"] = (
                performance.get("cache_lookup_ms", 0.0) + double_checked.lookup_ms
            )
        vector = validate_embedding(double_checked.value, dimension)
        if vector is not None:
            release_lock(key, token, settings=settings)
            if performance is not None:
                performance["embedding_cache_status"] = "hit_after_lock"
                performance["embedding_ms"] = (time.perf_counter() - started) * 1000
            return vector
    if token is None and cached.status == "miss":
        waited = bounded_wait_for_json(key, settings=settings)
        if performance is not None:
            performance["cache_lookup_ms"] = performance.get("cache_lookup_ms", 0.0) + waited.lookup_ms
        vector = validate_embedding(waited.value, dimension)
        if vector is not None:
            if performance is not None:
                performance["embedding_cache_status"] = "hit_after_wait"
                performance["embedding_ms"] = (time.perf_counter() - started) * 1000
            return vector
    try:
        vector = _encode_query(model, query)
        if len(vector) == dimension and dimension > 0:
            write_json(
                key,
                {"dimension": dimension, "vector": vector},
                settings.embedding_ttl_seconds,
                settings,
            )
        if performance is not None:
            performance["embedding_ms"] = (time.perf_counter() - started) * 1000
        return vector
    finally:
        release_lock(key, token, settings=settings)


def _semantic_cache_key(query: str, top_k: int, generation: int) -> str:
    settings = get_cache_settings()
    return retrieval_cache_key(
        settings,
        retrieval_mode="semantic",
        query=query,
        top_k=top_k,
        filters={},
        collection_name=MILVUS_COLLECTION,
        embedding_model=EMBEDDING_MODEL,
        retrieval_config=SEMANTIC_RETRIEVAL_CONFIG,
        knowledge_generation=generation,
    )


def search_chunks(
    query: str,
    top_k: int = 5,
    performance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    settings = get_cache_settings()
    generation_started = time.perf_counter()
    generation = get_knowledge_generation(settings)
    key = _semantic_cache_key(query, top_k, generation)
    cached = read_json(key, settings)
    if performance is not None:
        performance["cache_lookup_ms"] = (
            performance.get("cache_lookup_ms", 0.0)
            + (time.perf_counter() - generation_started) * 1000
            + cached.lookup_ms
        )
        performance["cache_status"] = cached.status
        performance["cache_hit"] = False
    hits = validate_retrieval_payload(cached.value, top_k)
    if hits is not None:
        if performance is not None:
            performance["cache_hit"] = True
            performance["cache_status"] = "hit"
        return hits
    if cached.value is not None:
        delete_key(key, settings)

    token = acquire_lock(key, settings=settings)
    if token is not None:
        double_checked = read_json(key, settings)
        if performance is not None:
            performance["cache_lookup_ms"] += double_checked.lookup_ms
        hits = validate_retrieval_payload(double_checked.value, top_k)
        if hits is not None:
            release_lock(key, token, settings=settings)
            if performance is not None:
                performance["cache_hit"] = True
                performance["cache_status"] = "hit_after_lock"
            return hits
    if token is None and cached.status == "miss":
        waited = bounded_wait_for_json(key, settings=settings)
        if performance is not None:
            performance["cache_lookup_ms"] += waited.lookup_ms
        hits = validate_retrieval_payload(waited.value, top_k)
        if hits is not None:
            if performance is not None:
                performance["cache_hit"] = True
                performance["cache_status"] = "hit_after_wait"
            return hits
    try:
        query_vector = embed_query(query, performance=performance)
        milvus_started = time.perf_counter()
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
        if performance is not None:
            performance["milvus_ms"] = (time.perf_counter() - milvus_started) * 1000

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
        stored = write_json(
            key, {"results": hits}, settings.search_ttl_seconds, settings
        )
        if performance is not None:
            performance["_cache_key"] = key
            performance["_cache_settings"] = settings
            performance["_cache_written"] = stored
        return hits
    finally:
        release_lock(key, token, settings=settings)
