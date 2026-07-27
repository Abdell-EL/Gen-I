from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.retrieval import RetrievalService
from app.services.admin_ingestion_service import (
    AdminIngestionError,
    get_ingestion_job_detail,
    ingest_docx_bytes,
    list_ingestion_jobs,
)
from app.services.answer_service import compose_answer
from app.services.retrieval_logging_service import (
    get_latest_retrievals,
    get_retrieval_detail,
    log_retrieval_event,
)
from app.services.retrieval_service import search_chunks
from app.services.system_health_service import get_system_health, get_system_stats
from app.services.ollama_service import generate_answer_with_ollama




router = APIRouter()
retrieval_service = RetrievalService()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)


class AuditRef(BaseModel):
    audit_logged: bool
    retrieval_id: int | None = None
    user_id: int | None = None
    session_id: int | None = None
    message_id: int | None = None
    logged_results: int = 0
    missing_chunk_ids: list[str] = []


class SourcePreview(BaseModel):
    rank: int | None = None
    score: float | None = None
    id: str | None = None
    kb_code: str | None = None
    article_title: str | None = None
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


def compact_audit(audit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not audit:
        return None

    return {
        "audit_logged": audit.get("audit_logged", False),
        "retrieval_id": audit.get("retrieval_id"),
        "user_id": audit.get("user_id"),
        "session_id": audit.get("session_id"),
        "message_id": audit.get("message_id"),
        "logged_results": audit.get("logged_results", 0),
        "missing_chunk_ids": audit.get("missing_chunk_ids", []),
    }


def compact_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "score": item.get("score"),
        "id": item.get("id") or item.get("external_chunk_id"),
        "kb_code": item.get("kb_code"),
        "article_title": item.get("article_title"),
        "section_title": item.get("section_title"),
        "chunk_type": item.get("chunk_type"),
        "priority": item.get("priority"),
        "text": item.get("text"),
    }


@router.get("/health")
def health_check():
    return get_system_health()


@router.get("/stats")
def get_stats():
    return get_system_stats(fallback_stats=retrieval_service.get_stats)


@router.post("/admin/ingestion/docx", response_model=AdminIngestionSummary)
async def admin_ingest_docx(file: UploadFile = File(...)):
    # Admin RBAC belongs here once authentication enforcement is enabled.
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
def admin_list_ingestion_jobs(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return list_ingestion_jobs(limit=limit)

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load ingestion jobs: {str(error)}",
        )


@router.get("/admin/ingestion/jobs/{job_id}", response_model=AdminIngestionJobDetail)
def admin_get_ingestion_job(job_id: int):
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


@router.post("/search", response_model=SearchResponse)
def semantic_search(request: SearchRequest):
    try:
        results = search_chunks(
            query=request.query,
            top_k=request.limit,
        )

        audit = log_retrieval_event(
            query_text=request.query,
            top_k=request.limit,
            retrieved_chunks=results,
            interaction_type="search",
        )

        compact_results = [compact_source(item) for item in results]

        return {
            "query": request.query,
            "search_type": "semantic_vector_search",
            "top_k": request.limit,
            "results_count": len(compact_results),
            "results": compact_results,
            "audit": compact_audit(audit),
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Semantic search failed: {str(error)}",
        )


@router.post("/keyword-search", response_model=SearchResponse)
def keyword_search(request: SearchRequest):
    results = retrieval_service.keyword_search(
        query=request.query,
        limit=request.limit,
    )

    compact_results = [compact_source(item) for item in results]

    return {
        "query": request.query,
        "search_type": "keyword_search",
        "top_k": request.limit,
        "results_count": len(compact_results),
        "results": compact_results,
        "audit": None,
    }

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        retrieved_chunks = search_chunks(
            query=request.question,
            top_k=5,
        )

        fallback_payload = compose_answer(
            question=request.question,
            retrieved_chunks=retrieved_chunks,
        )

        generation_provider = "ollama"
        generation_model = None
        generation_error = None

        try:
            answer_payload = generate_answer_with_ollama(
                question=request.question,
                retrieved_chunks=retrieved_chunks,
            )

            answer = answer_payload["answer"]
            generation_model = answer_payload.get("model")

        except Exception as error:
            answer = fallback_payload["answer"]
            generation_provider = "rule_based_fallback"
            generation_model = None
            generation_error = str(error)

        audit = log_retrieval_event(
            query_text=request.question,
            top_k=5,
            retrieved_chunks=retrieved_chunks,
            interaction_type="chat",
        )

        compact_sources = [compact_source(item) for item in retrieved_chunks]

        return {
            "question": request.question,
            "answer": answer,
            "confidence": fallback_payload["confidence"],
            "sources": compact_sources,
            "audit": compact_audit(audit),
            "generation_provider": generation_provider,
            "generation_model": generation_model,
            "generation_error": generation_error,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Chat retrieval failed: {str(error)}",
        )


@router.get("/audit/retrievals/latest")
def latest_retrievals(limit: int = 10):
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
def retrieval_detail(retrieval_id: int):
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
