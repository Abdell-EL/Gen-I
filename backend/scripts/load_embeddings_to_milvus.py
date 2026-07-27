import json
import os
from pathlib import Path
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMBEDDINGS_PATH = PROJECT_ROOT / "data" / "processed" / "embeddings.jsonl"

MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION", "sogetrel_chunks")

VECTOR_DIM = 1024
BATCH_SIZE = 200
DROP_EXISTING = os.getenv("MILVUS_DROP_EXISTING", "true").lower() in {"true", "1", "yes"}


def safe_str(value: Any, max_len: int = 1024) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:max_len]


def load_jsonl(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Embeddings file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)

            embedding = row.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError(f"Missing embedding at line {line_number}")

            if len(embedding) != VECTOR_DIM:
                raise ValueError(
                    f"Invalid vector dimension at line {line_number}: "
                    f"expected {VECTOR_DIM}, got {len(embedding)}"
                )

            metadata = row.get("metadata") or {}

            yield {
                "id": safe_str(row.get("id"), 256),
                "text": safe_str(row.get("text"), 8192),
                "kb_code": safe_str(metadata.get("kb_code"), 256),
                "article_title": safe_str(metadata.get("article_title"), 1024),
                "section_title": safe_str(metadata.get("section_title"), 512),
                "chunk_type": safe_str(metadata.get("chunk_type"), 128),
                "priority": safe_str(metadata.get("priority"), 128),
                "metadata": metadata,
                "embedding": [float(x) for x in embedding],
            }


def create_collection() -> Collection:
    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)

    if utility.has_collection(COLLECTION_NAME):
        if DROP_EXISTING:
            print(f"Dropping existing collection: {COLLECTION_NAME}")
            utility.drop_collection(COLLECTION_NAME)
        else:
            print(f"Using existing collection: {COLLECTION_NAME}")
            return Collection(COLLECTION_NAME)

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
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
    ]

    schema = CollectionSchema(
        fields=fields,
        description="Sogetrel KB/FDE chunks with BGE-M3 embeddings",
        enable_dynamic_field=False,
    )

    collection = Collection(name=COLLECTION_NAME, schema=schema)

    index_params = {
        "metric_type": "COSINE",
        "index_type": "AUTOINDEX",
        "params": {},
    }

    collection.create_index(field_name="embedding", index_params=index_params)
    print(f"Created collection: {COLLECTION_NAME}")

    return collection


def insert_batches(collection: Collection) -> int:
    batch = []
    inserted = 0

    for row in load_jsonl(EMBEDDINGS_PATH):
        batch.append(row)

        if len(batch) >= BATCH_SIZE:
            collection.insert(batch)
            inserted += len(batch)
            print(f"Inserted {inserted} vectors...")
            batch.clear()

    if batch:
        collection.insert(batch)
        inserted += len(batch)
        print(f"Inserted {inserted} vectors...")

    collection.flush()
    collection.load()

    return inserted


def main():
    print(f"Connecting to Milvus at {MILVUS_HOST}:{MILVUS_PORT}")
    print(f"Embeddings file: {EMBEDDINGS_PATH}")

    collection = create_collection()
    inserted = insert_batches(collection)

    print("Milvus load completed.")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Inserted vectors: {inserted}")
    print(f"Milvus entity count: {collection.num_entities}")


if __name__ == "__main__":
    main()