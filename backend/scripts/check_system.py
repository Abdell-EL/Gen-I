import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pymilvus import Collection, connections, utility
from sqlalchemy import text

from app.config import MILVUS_COLLECTION, MILVUS_HOST, MILVUS_PORT
from app.database import SessionLocal
from app.services.answer_service import compose_answer
from app.services.retrieval_service import search_chunks


MIN_EXPECTED_CHUNKS = 2345
MIN_EXPECTED_DOCUMENTS = 30


def check_postgres() -> int:
    db = SessionLocal()

    try:
        chunks_count = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar_one()
        documents_count = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM source_documents
                WHERE processing_status = 'completed'
                """
            )
        ).scalar_one()

        print("PostgreSQL connection: OK")
        print(f"PostgreSQL chunks: {chunks_count}")
        print(f"PostgreSQL completed source documents: {documents_count}")

        if chunks_count < MIN_EXPECTED_CHUNKS:
            raise RuntimeError(f"Expected at least {MIN_EXPECTED_CHUNKS} chunks, got {chunks_count}")

        if documents_count < MIN_EXPECTED_DOCUMENTS:
            raise RuntimeError(
                f"Expected at least {MIN_EXPECTED_DOCUMENTS} completed source documents, "
                f"got {documents_count}"
            )

        return chunks_count

    finally:
        db.close()


def check_milvus(expected_chunks: int) -> None:
    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)

    collections = utility.list_collections()

    print("Milvus connection: OK")
    print(f"Milvus collections: {collections}")

    if MILVUS_COLLECTION not in collections:
        raise RuntimeError(f"Milvus collection not found: {MILVUS_COLLECTION}")

    collection = Collection(MILVUS_COLLECTION)
    collection.load()

    entity_count = collection.num_entities

    print(f"Milvus vectors: {entity_count}")

    if entity_count != expected_chunks:
        raise RuntimeError(f"Expected {expected_chunks} vectors, got {entity_count}")


def check_retrieval() -> None:
    query = "Quel code situation utiliser pour une demande d'autorisation voisinage ?"

    results = search_chunks(query=query, top_k=5)

    if not results:
        raise RuntimeError("Retrieval returned no results")

    answer_payload = compose_answer(
        question=query,
        retrieved_chunks=results,
    )

    answer = answer_payload.get("answer", "")
    top_result = results[0]

    print("Semantic retrieval: OK")
    print(f"Top result ID: {top_result.get('id')}")
    print(f"Top score: {top_result.get('score')}")
    print(f"Answer: {answer}")

    if "AV" not in answer:
        raise RuntimeError("Expected answer to contain code situation AV")


def main() -> None:
    print("=" * 80)
    print("SOGESTREL KNOWLEDGE PLATFORM SYSTEM CHECK")
    print("=" * 80)

    chunks_count = check_postgres()
    print("-" * 80)

    check_milvus(expected_chunks=chunks_count)
    print("-" * 80)

    check_retrieval()
    print("-" * 80)

    print("SYSTEM CHECK PASSED")


if __name__ == "__main__":
    main()
