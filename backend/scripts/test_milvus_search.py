import json
from pathlib import Path

from pymilvus import Collection, connections


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMBEDDINGS_PATH = PROJECT_ROOT / "data" / "processed" / "embeddings.jsonl"

COLLECTION_NAME = "sogetrel_chunks"


def main():
    connections.connect(alias="default", host="127.0.0.1", port="19530")

    collection = Collection(COLLECTION_NAME)
    collection.load()

    with EMBEDDINGS_PATH.open("r", encoding="utf-8") as f:
        first_row = json.loads(next(f))

    query_vector = first_row["embedding"]

    results = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {}},
        limit=5,
        output_fields=[
            "id",
            "text",
            "kb_code",
            "article_title",
            "section_title",
            "chunk_type",
            "priority",
        ],
    )

    for i, hit in enumerate(results[0], start=1):
        entity = hit.entity
        print("=" * 80)
        print(f"Rank: {i}")
        print(f"Score: {hit.distance}")
        print(f"ID: {entity.get('id')}")
        print(f"KB Code: {entity.get('kb_code')}")
        print(f"Article: {entity.get('article_title')}")
        print(f"Section: {entity.get('section_title')}")
        print(f"Type: {entity.get('chunk_type')}")
        print(f"Priority: {entity.get('priority')}")
        print(f"Text: {entity.get('text')}")


if __name__ == "__main__":
    main()