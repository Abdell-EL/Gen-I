from collections.abc import Callable
from typing import Any

from pymilvus import Collection, connections, utility
from sqlalchemy import text

from app.config import MILVUS_COLLECTION, MILVUS_HOST, MILVUS_PORT
from app.database import SessionLocal


def check_postgres_health() -> dict[str, Any]:
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
        embeddings_count = db.execute(text("SELECT COUNT(*) FROM embeddings")).scalar_one()
        retrievals_count = db.execute(text("SELECT COUNT(*) FROM retrieval_requests")).scalar_one()

        status = "healthy" if chunks_count > 0 and documents_count > 0 else "degraded"

        return {
            "status": status,
            "connected": True,
            "chunks_count": chunks_count,
            "expected_chunks": chunks_count,
            "source_documents_count": documents_count,
            "expected_source_documents": documents_count,
            "embeddings_count": embeddings_count,
            "retrieval_requests_count": retrievals_count,
        }

    except Exception as error:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": str(error),
        }

    finally:
        db.close()


def check_milvus_health(expected_vectors: int | None = None) -> dict[str, Any]:
    try:
        connections.connect(
            alias="default",
            host=MILVUS_HOST,
            port=MILVUS_PORT,
        )

        collections = utility.list_collections()

        if MILVUS_COLLECTION not in collections:
            return {
                "status": "unhealthy",
                "connected": True,
                "collection_exists": False,
                "collection": MILVUS_COLLECTION,
                "collections": collections,
                "error": f"Collection not found: {MILVUS_COLLECTION}",
            }

        collection = Collection(MILVUS_COLLECTION)
        collection.load()

        vectors_count = collection.num_entities
        status = "healthy"

        if expected_vectors is not None and vectors_count != expected_vectors:
            status = "degraded"

        return {
            "status": status,
            "connected": True,
            "collection_exists": True,
            "collection": MILVUS_COLLECTION,
            "vectors_count": vectors_count,
            "expected_vectors": expected_vectors if expected_vectors is not None else vectors_count,
        }

    except Exception as error:
        return {
            "status": "unhealthy",
            "connected": False,
            "collection": MILVUS_COLLECTION,
            "error": str(error),
        }


def get_system_health() -> dict[str, Any]:
    postgres = check_postgres_health()
    expected_vectors = postgres.get("chunks_count") if postgres.get("connected") else None
    milvus = check_milvus_health(expected_vectors=expected_vectors)

    component_statuses = [
        postgres["status"],
        milvus["status"],
    ]

    if all(status == "healthy" for status in component_statuses):
        overall_status = "healthy"
    elif any(status == "healthy" for status in component_statuses):
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "service": "Sogetrel Knowledge Platform",
        "version": "0.1.0",
        "components": {
            "postgres": postgres,
            "milvus": milvus,
        },
    }


def get_system_stats(fallback_stats: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    db = SessionLocal()

    try:
        articles = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM source_documents
                WHERE processing_status = 'completed'
                """
            )
        ).scalar_one()
        chunks = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar_one()
        embeddings = db.execute(text("SELECT COUNT(*) FROM embeddings")).scalar_one()

        stats: dict[str, Any] = {
            "articles": articles,
            "chunks": chunks,
            "vector_collection": MILVUS_COLLECTION,
            "embeddings": embeddings,
        }

        try:
            milvus = check_milvus_health(expected_vectors=chunks)
            stats["vectors"] = milvus.get("vectors_count")
            stats["milvus_status"] = milvus.get("status")
        except Exception as error:
            stats["milvus_status"] = "unhealthy"
            stats["milvus_error"] = str(error)

        return stats

    except Exception:
        if fallback_stats is None:
            raise

        stats = fallback_stats()
        stats["vector_collection"] = MILVUS_COLLECTION
        stats["source"] = "file_fallback"
        return stats

    finally:
        db.close()
