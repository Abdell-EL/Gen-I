import json
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.config import MILVUS_COLLECTION, MILVUS_HOST, MILVUS_PORT


BATCH_SIZE = 200


def safe_str(value: Any, max_len: int = 1024) -> str:
    if value is None:
        return ""

    return str(value)[:max_len]


def _connect() -> None:
    connections.connect(
        alias="default",
        host=MILVUS_HOST,
        port=MILVUS_PORT,
    )


def _create_collection(collection_name: str, dimension: int) -> Collection:
    fields = [
        FieldSchema(
            name="id",
            dtype=DataType.VARCHAR,
            is_primary=True,
            auto_id=False,
            max_length=256,
        ),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="kb_code", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="article_title", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="priority", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="metadata", dtype=DataType.JSON),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
    ]

    schema = CollectionSchema(
        fields=fields,
        description="Sogetrel KB/FDE chunks with BGE-M3 embeddings",
        enable_dynamic_field=False,
    )

    collection = Collection(name=collection_name, schema=schema)
    collection.create_index(
        field_name="embedding",
        index_params={
            "metric_type": "COSINE",
            "index_type": "AUTOINDEX",
            "params": {},
        },
    )

    return collection


def get_or_create_collection(dimension: int) -> Collection:
    _connect()

    if utility.has_collection(MILVUS_COLLECTION):
        collection = Collection(MILVUS_COLLECTION)
    else:
        collection = _create_collection(MILVUS_COLLECTION, dimension)

    collection.load()
    return collection


def _id_expr(ids: list[str]) -> str:
    return f"id in {json.dumps(ids)}"


def find_existing_vector_ids(ids: list[str], dimension: int) -> set[str]:
    clean_ids = [safe_str(item, 256) for item in ids if item]

    if not clean_ids:
        return set()

    collection = get_or_create_collection(dimension=dimension)
    rows = collection.query(
        expr=_id_expr(clean_ids),
        output_fields=["id"],
    )

    return {str(row["id"]) for row in rows}


def _to_milvus_row(record: dict[str, Any], dimension: int) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    embedding = record.get("embedding")
    vector_id = str(record.get("id") or "").strip()

    if not vector_id:
        raise ValueError("Missing Milvus vector ID.")

    if len(vector_id) > 256:
        raise ValueError(f"Milvus vector ID is too long: {vector_id}")

    if not isinstance(embedding, list):
        raise ValueError(f"Missing embedding for vector {vector_id}")

    if len(embedding) != dimension:
        raise ValueError(
            f"Invalid vector dimension for {vector_id}: "
            f"expected {dimension}, got {len(embedding)}"
        )

    return {
        "id": vector_id,
        "text": safe_str(record.get("text"), 8192),
        "kb_code": safe_str(metadata.get("kb_code"), 256),
        "article_title": safe_str(metadata.get("article_title"), 1024),
        "section_title": safe_str(metadata.get("section_title"), 512),
        "chunk_type": safe_str(metadata.get("chunk_type"), 128),
        "priority": safe_str(metadata.get("priority"), 128),
        "metadata": metadata,
        "embedding": [float(value) for value in embedding],
    }


def insert_embedding_records(records: list[dict[str, Any]], dimension: int) -> int:
    if not records:
        return 0

    rows = [_to_milvus_row(record, dimension=dimension) for record in records]
    existing_ids = find_existing_vector_ids(
        ids=[row["id"] for row in rows],
        dimension=dimension,
    )

    if existing_ids:
        joined = ", ".join(sorted(existing_ids)[:5])
        raise ValueError(f"Milvus vector ID already exists: {joined}")

    collection = get_or_create_collection(dimension=dimension)
    inserted = 0
    inserted_ids: list[str] = []

    try:
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start:start + BATCH_SIZE]
            collection.insert(batch)
            inserted += len(batch)
            inserted_ids.extend(row["id"] for row in batch)

    except Exception:
        if inserted_ids:
            collection.delete(expr=_id_expr(inserted_ids))
            collection.flush()
        raise

    collection.flush()
    collection.load()

    return inserted


def delete_vectors(ids: list[str], dimension: int) -> None:
    clean_ids = [safe_str(item, 256) for item in ids if item]

    if not clean_ids:
        return

    collection = get_or_create_collection(dimension=dimension)
    collection.delete(expr=_id_expr(clean_ids))
    collection.flush()
