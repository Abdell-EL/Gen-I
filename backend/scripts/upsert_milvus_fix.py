"""Surgical Milvus upsert for the 32 corrected SBL-TRAIT-029/F04-P03-003
chunks -- NOT a full collection rebuild (load_embeddings_to_milvus.py drops
the whole collection by default, far too destructive for a 32-row fix).

Matches the real live schema (confirmed via describe_collection, since
scripts/embeddings.py's own --write-milvus path uses stale field names that
don't match it): id, text, kb_code, article_title, section_title,
chunk_type, priority, metadata (JSON), embedding (FLOAT_VECTOR dim=1024).

Run inside the api container:
  docker exec -w /app lab_api python scripts/upsert_milvus_fix.py
"""
import json

from pymilvus import MilvusClient

INPUT_PATH = "/tmp/sbl_f04_fix_embeddings.jsonl"
COLLECTION = "sogetrel_chunks"
MILVUS_URI = "http://milvus:19530"


def main() -> None:
    client = MilvusClient(uri=MILVUS_URI)

    rows = []
    with open(INPUT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            metadata = record["metadata"]
            rows.append({
                "id": record["id"],
                "text": record["text"],
                "kb_code": metadata["kb_code"],
                "article_title": metadata["article_title"],
                "section_title": metadata["section_title"],
                "chunk_type": metadata["chunk_type"],
                "priority": metadata["priority"],
                "metadata": metadata,
                "embedding": record["embedding"],
            })

    print(f"Upserting {len(rows)} rows into {COLLECTION}...")
    result = client.upsert(collection_name=COLLECTION, data=rows)
    print("Result:", result)

    client.flush(COLLECTION)
    print("Flushed.")


if __name__ == "__main__":
    main()
