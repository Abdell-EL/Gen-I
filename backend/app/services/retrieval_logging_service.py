import json
from typing import Any

from sqlalchemy import text

from app.database import SessionLocal


class ChatSessionAccessError(PermissionError):
    """Raised when a chat session does not belong to the active user."""


def _verify_owned_chat_session(db, session_id: int, user_id: int) -> int:
    result = db.execute(
        text(
            """
            SELECT session_id
            FROM chat_sessions
            WHERE session_id = :session_id
              AND user_id = :user_id
            LIMIT 1
            """
        ),
        {"session_id": session_id, "user_id": user_id},
    )
    value = result.scalar_one_or_none()
    if value is None:
        raise ChatSessionAccessError("Chat session is not available.")
    return int(value)


def ensure_chat_session_access(*, session_id: int, user_id: int) -> int:
    db = SessionLocal()
    try:
        return _verify_owned_chat_session(db=db, session_id=session_id, user_id=user_id)
    finally:
        db.close()


def _create_chat_session(db, user_id: int, title: str) -> int:
    result = db.execute(
        text(
            """
            INSERT INTO chat_sessions (user_id, title)
            VALUES (:user_id, :title)
            RETURNING session_id
            """
        ),
        {
            "user_id": user_id,
            "title": title,
        },
    )

    return int(result.scalar_one())


def _create_user_message(db, session_id: int, content: str) -> int:
    result = db.execute(
        text(
            """
            INSERT INTO chat_messages (session_id, role, content, model_name)
            VALUES (:session_id, :role, :content, :model_name)
            RETURNING message_id
            """
        ),
        {
            "session_id": session_id,
            "role": "user",
            "content": content,
            "model_name": "semantic-retrieval",
        },
    )

    return int(result.scalar_one())


def _create_assistant_message(db, session_id: int, answer: str, model_name: str | None) -> int:
    result = db.execute(text("""
        INSERT INTO chat_messages (session_id, role, content, model_name)
        VALUES (:session_id, 'assistant', :content, :model_name)
        RETURNING message_id
    """), {"session_id": session_id, "content": answer, "model_name": model_name})
    return int(result.scalar_one())


def create_assistant_message(*, session_id: int, answer: str = "", model_name: str | None = None) -> int:
    db = SessionLocal()
    try:
        message_id = _create_assistant_message(
            db, session_id=session_id, answer=answer, model_name=model_name,
        )
        db.commit()
        return message_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def log_assistant_message(*, session_id: int, answer: str, model_name: str | None) -> int:
    return create_assistant_message(
        session_id=session_id,
        answer=answer,
        model_name=model_name,
    )


def update_assistant_message(
    *,
    message_id: int,
    session_id: int,
    answer: str,
    model_name: str | None,
) -> None:
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                """
                UPDATE chat_messages
                SET content = :content,
                    model_name = :model_name
                WHERE message_id = :message_id
                  AND session_id = :session_id
                  AND role = 'assistant'
                """
            ),
            {
                "message_id": message_id,
                "session_id": session_id,
                "content": answer,
                "model_name": model_name,
            },
        )
        if result.rowcount != 1:
            raise ChatSessionAccessError("Assistant message is not available.")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _create_retrieval_request(
    db,
    message_id: int,
    user_id: int,
    query_text: str,
    top_k: int,
    interaction_type: str,
) -> int:
    retriever_config = {
        "interaction_type": interaction_type,
        "search_type": "semantic_vector_search",
        "metric_type": "COSINE",
    }

    result = db.execute(
        text(
            """
            INSERT INTO retrieval_requests (
                message_id,
                user_id,
                query_text,
                top_k,
                filters_json,
                embedding_model,
                milvus_collection,
                retriever_config_json
            )
            VALUES (
                :message_id,
                :user_id,
                :query_text,
                :top_k,
                CAST(:filters_json AS JSON),
                :embedding_model,
                :milvus_collection,
                CAST(:retriever_config_json AS JSON)
            )
            RETURNING retrieval_id
            """
        ),
        {
            "message_id": message_id,
            "user_id": user_id,
            "query_text": query_text,
            "top_k": top_k,
            "filters_json": json.dumps({}),
            "embedding_model": "BAAI/bge-m3",
            "milvus_collection": "sogetrel_chunks",
            "retriever_config_json": json.dumps(retriever_config),
        },
    )

    return int(result.scalar_one())


def _find_chunk_id_by_external_id(db, external_chunk_id: str) -> int | None:
    result = db.execute(
        text(
            """
            SELECT chunk_id
            FROM chunks
            WHERE metadata_json->>'external_chunk_id' = :external_chunk_id
            LIMIT 1
            """
        ),
        {
            "external_chunk_id": external_chunk_id,
        },
    )

    value = result.scalar_one_or_none()

    if value is None:
        return None

    return int(value)


def _insert_retrieval_result(
    db,
    retrieval_id: int,
    chunk_id: int,
    similarity_score: float,
    rank: int,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO retrieval_results (
                retrieval_id,
                chunk_id,
                similarity_score,
                rank
            )
            VALUES (
                :retrieval_id,
                :chunk_id,
                :similarity_score,
                :rank
            )
            """
        ),
        {
            "retrieval_id": retrieval_id,
            "chunk_id": chunk_id,
            "similarity_score": similarity_score,
            "rank": rank,
        },
    )


def log_retrieval_event(
    *,
    actor_user_id: int,
    query_text: str,
    top_k: int,
    retrieved_chunks: list[dict[str, Any]],
    interaction_type: str,
    session_id: int | None = None,
) -> dict[str, Any]:
    if (
        isinstance(actor_user_id, bool)
        or not isinstance(actor_user_id, int)
        or actor_user_id <= 0
    ):
        raise ValueError("actor_user_id must be a positive integer")

    db = SessionLocal()

    try:
        if session_id is None:
            session_id = _create_chat_session(
                db=db,
                user_id=actor_user_id,
                title=f"{interaction_type}: {query_text[:80]}",
            )
        else:
            session_id = _verify_owned_chat_session(
                db=db,
                session_id=session_id,
                user_id=actor_user_id,
            )
        message_id = _create_user_message(
            db=db,
            session_id=session_id,
            content=query_text,
        )
        retrieval_id = _create_retrieval_request(
            db=db,
            message_id=message_id,
            user_id=actor_user_id,
            query_text=query_text,
            top_k=top_k,
            interaction_type=interaction_type,
        )

        logged_results = 0
        missing_chunk_ids = []

        for item in retrieved_chunks:
            external_chunk_id = item.get("id") or item.get("external_chunk_id")

            if not external_chunk_id:
                continue

            chunk_id = _find_chunk_id_by_external_id(db, external_chunk_id)

            if chunk_id is None:
                missing_chunk_ids.append(external_chunk_id)
                continue

            _insert_retrieval_result(
                db=db,
                retrieval_id=retrieval_id,
                chunk_id=chunk_id,
                similarity_score=float(item.get("score") or 0.0),
                rank=int(item.get("rank") or 0),
            )

            logged_results += 1

        db.commit()

        return {
            "audit_logged": True,
            "retrieval_id": retrieval_id,
            "user_id": actor_user_id,
            "session_id": session_id,
            "message_id": message_id,
            "user_message_id": message_id,
            "logged_results": logged_results,
            "missing_chunk_ids": missing_chunk_ids,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    serialized = {}

    for key, value in row.items():
        if hasattr(value, "isoformat"):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value

    return serialized


def get_latest_retrievals(limit: int = 10) -> list[dict[str, Any]]:
    db = SessionLocal()

    try:
        result = db.execute(
            text(
                """
                SELECT
                    rr.retrieval_id,
                    rr.query_text,
                    rr.top_k,
                    rr.embedding_model,
                    rr.milvus_collection,
                    rr.created_at,
                    u.user_id,
                    u.full_name,
                    u.email,
                    COUNT(rres.retrieval_result_id) AS results_count,
                    MAX(rres.similarity_score) AS top_score
                FROM retrieval_requests rr
                JOIN users u ON rr.user_id = u.user_id
                LEFT JOIN retrieval_results rres
                    ON rr.retrieval_id = rres.retrieval_id
                GROUP BY
                    rr.retrieval_id,
                    rr.query_text,
                    rr.top_k,
                    rr.embedding_model,
                    rr.milvus_collection,
                    rr.created_at,
                    u.user_id,
                    u.full_name,
                    u.email
                ORDER BY rr.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

        return [
            _serialize_row(dict(row))
            for row in result.mappings().all()
        ]

    finally:
        db.close()


def get_retrieval_detail(retrieval_id: int) -> dict[str, Any] | None:
    db = SessionLocal()

    try:
        request_result = db.execute(
            text(
                """
                SELECT
                    rr.retrieval_id,
                    rr.query_text,
                    rr.top_k,
                    rr.filters_json,
                    rr.embedding_model,
                    rr.milvus_collection,
                    rr.retriever_config_json,
                    rr.created_at,
                    u.user_id,
                    u.full_name,
                    u.email,
                    cm.message_id,
                    cm.role AS message_role,
                    cm.content AS message_content
                FROM retrieval_requests rr
                JOIN users u ON rr.user_id = u.user_id
                JOIN chat_messages cm ON rr.message_id = cm.message_id
                WHERE rr.retrieval_id = :retrieval_id
                """
            ),
            {"retrieval_id": retrieval_id},
        )

        request_row = request_result.mappings().first()

        if request_row is None:
            return None

        results_result = db.execute(
            text(
                """
                SELECT
                    rres.rank,
                    rres.similarity_score,
                    c.chunk_id,
                    c.metadata_json->>'external_chunk_id' AS external_chunk_id,
                    c.chunk_text,
                    c.chunk_type,
                    c.metadata_json
                FROM retrieval_results rres
                JOIN chunks c ON rres.chunk_id = c.chunk_id
                WHERE rres.retrieval_id = :retrieval_id
                ORDER BY rres.rank ASC
                """
            ),
            {"retrieval_id": retrieval_id},
        )

        retrieved_chunks = [
            _serialize_row(dict(row))
            for row in results_result.mappings().all()
        ]

        return {
            "retrieval": _serialize_row(dict(request_row)),
            "results_count": len(retrieved_chunks),
            "results": retrieved_chunks,
        }

    finally:
        db.close()


def get_bounded_conversation_history(
    *,
    session_id: int,
    user_id: int,
    before_message_id: int,
    max_turns: int = 3,
    max_chars: int = 3000,
) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        _verify_owned_chat_session(db=db, session_id=session_id, user_id=user_id)
        result = db.execute(
            text(
                """
                SELECT message_id, role, content, created_at
                FROM chat_messages
                WHERE session_id = :session_id
                  AND message_id < :before_message_id
                  AND role IN ('user', 'assistant')
                ORDER BY message_id DESC
                LIMIT :limit
                """
            ),
            {
                "session_id": session_id,
                "before_message_id": before_message_id,
                "limit": max(0, max_turns) * 2,
            },
        )
        rows = [dict(row) for row in result.mappings().all()]
        rows.reverse()

        bounded_reversed = []
        used = 0
        for row in reversed(rows):
            content = str(row.get("content") or "")
            cost = len(content)
            if bounded_reversed and used + cost > max_chars:
                break
            if cost > max_chars:
                content = content[-max_chars:]
                cost = len(content)
                row["content"] = content
            bounded_reversed.append(row)
            used += cost
        bounded_reversed.reverse()
        return [_serialize_row(row) for row in bounded_reversed]
    finally:
        db.close()
