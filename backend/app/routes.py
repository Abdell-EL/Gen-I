from typing import Any, Iterator
import json
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse, StreamingResponse
import requests
from pydantic import BaseModel, Field

from app.auth_dependencies import require_any_role, require_role
from app.database import get_db
from app.models import User

from app.retrieval import RetrievalService
from app.services.admin_ingestion_service import (
    AdminIngestionError,
    get_ingestion_job_detail,
    ingest_docx_bytes,
    ingest_document_version_bytes,
    list_document_versions,
    list_ingestion_jobs,
)
from app.services.answer_service import compose_answer
from app.services.retrieval_logging_service import (
    ChatSessionAccessError,
    create_assistant_message,
    ensure_chat_session_access,
    get_bounded_conversation_history,
    get_latest_retrievals,
    get_retrieval_detail,
    log_assistant_message,
    log_retrieval_event,
    update_assistant_message,
)
from app.services.retrieval_service import search_chunks
from app.services.knowledge_article_service import (
    ArticleNotFoundError,
    OriginalDocumentNotFoundError,
    attach_source_database_metadata,
    get_article_detail,
    get_original_document_file,
)
from app.services.system_health_service import get_system_health, get_system_stats
from app.services.ollama_service import (
    generate_answer_with_ollama,
    stream_answer_with_ollama,
)
from app.services.performance_service import log_performance, new_performance_record
from app.services.cache_service import discard_new_retrieval_cache




router = APIRouter()
admin_or_agent = require_any_role("admin", "agent")
admin_only = require_role("admin")
retrieval_service = RetrievalService()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: int | None = Field(default=None, ge=1)


class AuditRef(BaseModel):
    audit_logged: bool
    retrieval_id: int | None = None
    user_id: int | None = None
    session_id: int | None = None
    message_id: int | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    logged_results: int = 0
    missing_chunk_ids: list[str] = []


class SourcePreview(BaseModel):
    rank: int | None = None
    score: float | None = None
    id: str | None = None
    chunk_id: int | None = None
    source_document_id: int | None = None
    document_version_id: int | None = None
    kb_code: str | None = None
    article_title: str | None = None
    file_name: str | None = None
    section_title: str | None = None
    chunk_type: str | None = None
    priority: str | None = None
    text: str | None = None


class SearchResponse(BaseModel):
    query: str
    search_type: str
    top_k: int
    results_count: int
    results: list[SourcePreview]
    audit: AuditRef | None = None


class ChatResponse(BaseModel):
    question: str
    answer: str
    confidence: str
    sources: list[SourcePreview]
    audit: AuditRef | None = None
    generation_provider: str | None = None
    generation_model: str | None = None
    generation_error: str | None = None


class ArticleSection(BaseModel):
    title: str
    chunk_ids: list[int]
    content: str


class RequestedChunkRef(BaseModel):
    chunk_id: int
    chunk_index: int
    section_title: str | None = None


class KnowledgeArticleResponse(BaseModel):
    source_document_id: int
    document_version_id: int
    current_document_version_id: int | None = None
    is_current_version: bool
    version_number: int
    title: str
    kb_code: str | None = None
    filename: str
    content: str
    sections: list[ArticleSection]
    created_at: Any | None = None
    uploaded_at: Any | None = None
    updated_at: Any | None = None
    requested_chunk: RequestedChunkRef | None = None


class AdminIngestionSummary(BaseModel):
    job_id: int
    status: str
    filename: str
    kb_code: str | None = None
    article_title: str | None = None
    document_id: int | None = None
    version_id: int | None = None
    chunks_created: int = 0
    embeddings_created: int = 0
    milvus_vectors_inserted: int = 0
    message: str


class AdminIngestionJobListItem(BaseModel):
    job_id: int
    job_type: str
    status: str
    source_path: str | None = None
    filename: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
    processed_documents: int = 0
    processed_chunks: int = 0
    error_message: str | None = None


class AdminIngestionJobDetail(AdminIngestionJobListItem):
    document_id: int | None = None
    version_id: int | None = None
    kb_code: str | None = None
    article_title: str | None = None
    chunks_created: int = 0
    embeddings_created: int = 0
    config_json: dict[str, Any] | None = None


class AdminDocumentVersionUpdateResponse(BaseModel):
    source_document_id: int
    document_version_id: int | None = None
    ingestion_job_id: int | None = None
    status: str
    filename: str
    kb_code: str | None = None
    article_title: str | None = None
    version_number: int | None = None
    chunks_created: int = 0
    embeddings_created: int = 0
    milvus_vectors_inserted: int = 0
    message: str


class AdminDocumentVersionListItem(BaseModel):
    source_document_id: int
    document_version_id: int
    version_number: int
    status: str
    is_current: bool
    filename: str
    uploaded_by: int | None = None
    uploaded_at: Any | None = None
    activated_at: Any | None = None
    superseded_at: Any | None = None
    change_reason: str | None = None
    change_summary: str | None = None
    effective_at: str | None = None
    ingestion_job_id: int | None = None
    ingestion_status: str | None = None
    chunks_created: int = 0
    embeddings_created: int = 0
    error_message: str | None = None


def compact_audit(audit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not audit:
        return None

    return {
        "audit_logged": audit.get("audit_logged", False),
        "retrieval_id": audit.get("retrieval_id"),
        "user_id": audit.get("user_id"),
        "session_id": audit.get("session_id"),
        "message_id": audit.get("assistant_message_id") or audit.get("message_id"),
        "user_message_id": audit.get("user_message_id") or audit.get("message_id"),
        "assistant_message_id": audit.get("assistant_message_id"),
        "logged_results": audit.get("logged_results", 0),
        "missing_chunk_ids": audit.get("missing_chunk_ids", []),
    }


def compact_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "score": item.get("score"),
        "id": item.get("id") or item.get("external_chunk_id"),
        "chunk_id": item.get("chunk_id"),
        "source_document_id": item.get("source_document_id") or item.get("document_id"),
        "document_version_id": item.get("document_version_id") or item.get("version_id"),
        "kb_code": item.get("kb_code"),
        "article_title": item.get("article_title"),
        "file_name": item.get("file_name") or item.get("source_filename"),
        "section_title": item.get("section_title"),
        "chunk_type": item.get("chunk_type"),
        "priority": item.get("priority"),
        "text": item.get("text"),
    }



def _validated_question(question: str) -> str:
    trimmed = question.strip()
    if not trimmed:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")
    return trimmed


def _prepare_chat_retrieval(
    *,
    request: ChatRequest,
    current_user: User,
    performance: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    question = _validated_question(request.question)
    if request.session_id is not None:
        ensure_chat_session_access(
            session_id=request.session_id,
            user_id=current_user.user_id,
        )
    retrieved_chunks = search_chunks(query=question, top_k=5, performance=performance)
    enriched_chunks = attach_source_database_metadata(retrieved_chunks)
    fallback_payload = compose_answer(question=question, retrieved_chunks=enriched_chunks)
    audit_started = time.perf_counter()
    audit = log_retrieval_event(
        actor_user_id=current_user.user_id,
        query_text=question,
        top_k=5,
        retrieved_chunks=enriched_chunks,
        interaction_type="chat",
        session_id=request.session_id,
    )
    performance["audit_ms"] = (time.perf_counter() - audit_started) * 1000
    history = get_bounded_conversation_history(
        session_id=audit["session_id"],
        user_id=current_user.user_id,
        before_message_id=audit["user_message_id"],
    )
    return question, enriched_chunks, fallback_payload, history, audit

def _performance_context(http_request: Request) -> tuple[float, str]:
    started = getattr(http_request.state, "performance_started", time.perf_counter())
    request_id = getattr(http_request.state, "request_id", str(uuid4()))
    return started, request_id


@router.get("/health")
def health_check():
    return get_system_health()


@router.get("/stats")
def get_stats(_current_user: User = Depends(admin_or_agent)):
    return get_system_stats(fallback_stats=retrieval_service.get_stats)


@router.post("/admin/ingestion/docx", response_model=AdminIngestionSummary)
async def admin_ingest_docx(
    file: UploadFile = File(...),
    _current_user: User = Depends(admin_only),
):
    try:
        content = await file.read()
        return ingest_docx_bytes(filename=file.filename, content=content)

    except AdminIngestionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.summary,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"DOCX ingestion failed: {str(error)}",
        )


@router.get("/admin/ingestion/jobs", response_model=list[AdminIngestionJobListItem])
def admin_list_ingestion_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(admin_only),
):
    try:
        return list_ingestion_jobs(limit=limit)

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load ingestion jobs: {str(error)}",
        )


@router.get("/admin/ingestion/jobs/{job_id}", response_model=AdminIngestionJobDetail)
def admin_get_ingestion_job(
    job_id: int,
    _current_user: User = Depends(admin_only),
):
    try:
        detail = get_ingestion_job_detail(job_id=job_id)

        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"Ingestion job {job_id} not found",
            )

        return detail

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load ingestion job: {str(error)}",
        )


@router.post(
    "/admin/knowledge/documents/{source_document_id}/versions",
    response_model=AdminDocumentVersionUpdateResponse,
)
async def admin_upload_document_version(
    source_document_id: int,
    file: UploadFile = File(...),
    change_reason: str | None = Form(default=None),
    change_summary: str | None = Form(default=None),
    effective_at: str | None = Form(default=None),
    current_user: User = Depends(admin_only),
):
    try:
        content = await file.read()
        return ingest_document_version_bytes(
            source_document_id=source_document_id,
            filename=file.filename,
            content=content,
            content_type=file.content_type,
            uploaded_by_user_id=current_user.user_id,
            change_reason=change_reason,
            change_summary=change_summary,
            effective_at=effective_at,
        )

    except AdminIngestionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.summary)

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"DOCX version update failed: {str(error)}",
        )


@router.get(
    "/admin/knowledge/documents/{source_document_id}/versions",
    response_model=list[AdminDocumentVersionListItem],
)
def admin_list_document_versions(
    source_document_id: int,
    _current_user: User = Depends(admin_only),
):
    try:
        versions = list_document_versions(source_document_id=source_document_id)
        if versions is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return versions

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load document versions: {str(error)}",
        )


@router.post("/search", response_model=SearchResponse)
def semantic_search(
    request: SearchRequest,
    http_request: Request,
    current_user: User = Depends(admin_or_agent),
):
    started, request_id = _performance_context(http_request)
    performance = new_performance_record()
    try:
        results = search_chunks(
            query=request.query,
            top_k=request.limit,
            performance=performance,
        )
        audit_started = time.perf_counter()
        audit = log_retrieval_event(
            actor_user_id=current_user.user_id,
            query_text=request.query,
            top_k=request.limit,
            retrieved_chunks=results,
            interaction_type="search",
        )
        performance["audit_ms"] = (time.perf_counter() - audit_started) * 1000
        compact_results = [compact_source(item) for item in results]
        response = {
            "query": request.query,
            "search_type": "semantic_vector_search",
            "top_k": request.limit,
            "results_count": len(compact_results),
            "results": compact_results,
            "audit": compact_audit(audit),
        }
        performance["total_ms"] = (time.perf_counter() - started) * 1000
        log_performance("search_performance", request_id, performance)
        return response
    except Exception as error:
        discard_new_retrieval_cache(performance)
        raise HTTPException(
            status_code=500,
            detail=f"Semantic search failed: {str(error)}",
        )


@router.post("/keyword-search", response_model=SearchResponse)
def keyword_search(
    request: SearchRequest,
    http_request: Request,
    current_user: User = Depends(admin_or_agent),
):
    started, request_id = _performance_context(http_request)
    performance = new_performance_record()
    results = retrieval_service.keyword_search(
        query=request.query,
        limit=request.limit,
        performance=performance,
    )
    audit_started = time.perf_counter()
    try:
        audit = log_retrieval_event(
            actor_user_id=current_user.user_id,
            query_text=request.query,
            top_k=request.limit,
            retrieved_chunks=results,
            interaction_type="keyword_search",
        )
    except Exception:
        discard_new_retrieval_cache(performance)
        raise
    performance["audit_ms"] = (time.perf_counter() - audit_started) * 1000
    compact_results = [compact_source(item) for item in results]
    response = {
        "query": request.query,
        "search_type": "keyword_search",
        "top_k": request.limit,
        "results_count": len(compact_results),
        "results": compact_results,
        "audit": compact_audit(audit),
    }
    performance["total_ms"] = (time.perf_counter() - started) * 1000
    log_performance("keyword_search_performance", request_id, performance)
    return response


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    http_request: Request,
    current_user: User = Depends(admin_or_agent),
):
    started, request_id = _performance_context(http_request)
    performance = new_performance_record()
    try:
        question, retrieved_chunks, fallback_payload, history, audit = _prepare_chat_retrieval(
            request=request,
            current_user=current_user,
            performance=performance,
        )
        generation_provider = "ollama"
        generation_model = None
        generation_error = None
        ollama_started = time.perf_counter()
        try:
            answer_payload = generate_answer_with_ollama(
                question=question,
                retrieved_chunks=retrieved_chunks,
                conversation_history=history,
            )
            answer = answer_payload["answer"]
            generation_model = answer_payload.get("model")
            for field in (
                "context_chunks_selected",
                "context_chunks_included",
                "context_chars",
            ):
                if field in answer_payload:
                    performance[field] = answer_payload[field]
        except Exception as error:
            answer = fallback_payload["answer"]
            generation_provider = "rule_based_fallback"
            generation_model = None
            generation_error = str(error)
        finally:
            performance["ollama_ms"] = (time.perf_counter() - ollama_started) * 1000

        try:
            assistant_message_id = log_assistant_message(
                session_id=audit["session_id"], answer=answer, model_name=generation_model,
            )
        except Exception:
            assistant_message_id = None
        audit["assistant_message_id"] = assistant_message_id
        compact_sources = [compact_source(item) for item in retrieved_chunks]
        response = {
            "question": question,
            "answer": answer,
            "confidence": fallback_payload["confidence"],
            "sources": compact_sources,
            "audit": compact_audit(audit),
            "generation_provider": generation_provider,
            "generation_model": generation_model,
            "generation_error": generation_error,
        }
        performance["total_ms"] = (time.perf_counter() - started) * 1000
        log_performance("chat_performance", request_id, performance)
        return response
    except ChatSessionAccessError as error:
        discard_new_retrieval_cache(performance)
        raise HTTPException(status_code=403, detail=str(error)) from None
    except HTTPException:
        discard_new_retrieval_cache(performance)
        raise
    except Exception as error:
        discard_new_retrieval_cache(performance)
        raise HTTPException(
            status_code=500,
            detail=f"Chat retrieval failed: {str(error)}",
        )

def _ndjson_event(event: dict[str, Any]) -> bytes:
    return (json.dumps(
        event,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ) + "\n").encode("utf-8")


@router.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    http_request: Request,
    current_user: User = Depends(admin_or_agent),
):
    started, request_id = _performance_context(http_request)
    performance = new_performance_record()
    try:
        question, retrieved_chunks, fallback_payload, history, audit = _prepare_chat_retrieval(
            request=request,
            current_user=current_user,
            performance=performance,
        )
        compact_sources = [compact_source(item) for item in retrieved_chunks]
        stream = stream_answer_with_ollama(
            question,
            retrieved_chunks,
            conversation_history=history,
        )
        assistant_message_id = create_assistant_message(
            session_id=audit["session_id"],
            answer="",
            model_name=stream.model,
        )
        audit["assistant_message_id"] = assistant_message_id
        performance.update(
            context_chunks_selected=stream.context_chunks_selected,
            context_chunks_included=stream.context_chunks_included,
            context_chars=stream.context_chars,
        )
    except ChatSessionAccessError as error:
        discard_new_retrieval_cache(performance)
        raise HTTPException(status_code=403, detail=str(error)) from None
    except HTTPException:
        discard_new_retrieval_cache(performance)
        raise
    except Exception:
        discard_new_retrieval_cache(performance)
        raise HTTPException(status_code=500, detail="Chat streaming could not be started.")

    def events() -> Iterator[bytes]:
        generation_started = time.perf_counter()
        first_token_at: float | None = None
        emitted_tokens = 0
        status = "complete"
        answer_parts: list[str] = []
        try:
            yield _ndjson_event(
                {
                    "type": "metadata",
                    "question": question,
                    "confidence": fallback_payload["confidence"],
                    "sources": compact_sources,
                    "audit": compact_audit(audit),
                    "generation_provider": "ollama",
                    "generation_model": stream.model,
                }
            )
            saw_done = False
            for item in stream.chunks():
                if item["type"] == "token":
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    emitted_tokens += 1
                    answer_parts.append(item["text"])
                    yield _ndjson_event(item)
                else:
                    saw_done = True
            if not emitted_tokens:
                status = "empty"
                yield _ndjson_event({
                    "type": "error", "code": "empty_stream",
                    "message": "No response was generated.",
                })
            elif not saw_done:
                status = "interrupted"
                yield _ndjson_event({
                    "type": "error", "code": "stream_interrupted",
                    "message": "The response stream ended early.",
                })
        except GeneratorExit:
            status = "client_disconnected"
            raise
        except requests.Timeout:
            status = "timeout"
            yield _ndjson_event({
                "type": "error", "code": "timeout",
                "message": "The response stream timed out.",
            })
        except requests.RequestException:
            status = "interrupted"
            yield _ndjson_event({
                "type": "error", "code": "stream_interrupted",
                "message": "The response stream ended early.",
            })
        except Exception:
            status = "failed"
            yield _ndjson_event({
                "type": "error", "code": "generation_failed",
                "message": "The response could not be completed.",
            })
        finally:
            finished = time.perf_counter()
            answer = "".join(answer_parts)
            try:
                update_assistant_message(
                    message_id=assistant_message_id,
                    session_id=audit["session_id"],
                    answer=answer,
                    model_name=stream.model,
                )
            except Exception:
                pass
            performance["time_to_first_token_ms"] = (
                (first_token_at - generation_started) * 1000
                if first_token_at is not None else 0.0
            )
            performance["generation_ms"] = (finished - generation_started) * 1000
            performance["ollama_ms"] = performance["generation_ms"]
            performance["total_ms"] = (finished - started) * 1000
            log_performance("chat_stream_performance", request_id, performance)
        if status != "client_disconnected":
            yield _ndjson_event({
                "type": "done", "status": status, "partial": status != "complete",
                "message_id": assistant_message_id,
                "assistant_message_id": assistant_message_id,
            })

    return StreamingResponse(
        events(), media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/knowledge/articles/{source_document_id}", response_model=KnowledgeArticleResponse)
def knowledge_article_detail(
    source_document_id: int,
    version_id: int | None = Query(default=None, ge=1),
    chunk_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(admin_or_agent),
    db: Session = Depends(get_db),
):
    try:
        return get_article_detail(
            db,
            source_document_id=source_document_id,
            current_user=current_user,
            version_id=version_id,
            chunk_id=chunk_id,
        )
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found.") from None


@router.get("/knowledge/documents/{source_document_id}/original")
def knowledge_original_document(
    source_document_id: int,
    version_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(admin_or_agent),
    db: Session = Depends(get_db),
):
    try:
        file_info = get_original_document_file(
            db,
            source_document_id=source_document_id,
            current_user=current_user,
            version_id=version_id,
        )
    except OriginalDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.") from None

    return FileResponse(
        path=file_info["path"],
        media_type=file_info["media_type"],
        filename=file_info["filename"],
        content_disposition_type="attachment",
    )

@router.get("/audit/retrievals/latest")
def latest_retrievals(
    limit: int = 10,
    _current_user: User = Depends(admin_only),
):
    try:
        limit = max(1, min(limit, 50))
        retrievals = get_latest_retrievals(limit=limit)

        return {
            "count": len(retrievals),
            "retrievals": retrievals,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load latest retrievals: {str(error)}",
        )


@router.get("/audit/retrievals/{retrieval_id}")
def retrieval_detail(
    retrieval_id: int,
    _current_user: User = Depends(admin_only),
):
    try:
        detail = get_retrieval_detail(retrieval_id=retrieval_id)

        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"Retrieval {retrieval_id} not found",
            )

        return detail

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load retrieval detail: {str(error)}",
        )
