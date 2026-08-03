from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import MILVUS_COLLECTION
from app.database import SessionLocal
from app.models import (
    Chunk,
    Department,
    DocumentSheet,
    DocumentVersion,
    Embedding,
    IngestionJob,
    KnowledgeBase,
    SourceDocument,
    AuditLog,
)
from app.services.milvus_writer_service import delete_vectors, insert_embedding_records
from app.services.cache_service import advance_knowledge_generation
from scripts.chunk import smart_chunk_article
from scripts.embeddings import (
    EmbeddingConfig,
    EmbeddingModel,
    build_embedding_text,
    build_metadata,
    stable_hash,
)
from scripts.ingest import build_article, validate_article


UPLOAD_ROOT = Path(os.getenv("KB_UPLOAD_ROOT", "data/uploads/kb_articles"))
DEFAULT_DEPARTMENT_CODE = os.getenv("DEFAULT_DEPARTMENT_CODE", "FDE")
DEFAULT_DEPARTMENT_NAME = os.getenv("DEFAULT_DEPARTMENT_NAME", "FDE")
DEFAULT_KB_NAME = os.getenv("DEFAULT_KB_NAME", "Base de connaissance FDE")
DEFAULT_KB_DESCRIPTION = "Knowledge base for FDE operational articles."
FATAL_VALIDATION_WARNINGS = {"empty_content", "missing_kb_code", "missing_title"}
MAX_DOCX_UPLOAD_BYTES = int(os.getenv("KB_DOCX_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))
DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "application/zip",
    "",
}


class AdminIngestionError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        summary: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.summary = summary or {"message": message}


def utc_now() -> datetime:
    return datetime.utcnow()


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_filename(filename: str | None) -> str:
    original = Path(filename or "article.docx").name
    suffix = Path(original).suffix.lower()
    stem = Path(original).stem
    clean_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")

    if not clean_stem:
        clean_stem = "article"

    return f"{clean_stem}{suffix}"


def _store_upload(filename: str, content: bytes, checksum: str) -> Path:
    date_dir = utc_now().strftime("%Y%m%d")
    destination_dir = UPLOAD_ROOT / date_dir / checksum[:12]
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / filename
    destination.write_bytes(content)

    return destination


def _validate_docx_upload(
    *,
    filename: str | None,
    content: bytes,
    content_type: str | None = None,
) -> str:
    safe_filename = _safe_filename(filename)
    suffix = Path(safe_filename).suffix.lower()

    if suffix != ".docx":
        raise AdminIngestionError(
            message="Only .docx uploads are supported.",
            status_code=400,
            summary={
                "status": "failed",
                "filename": safe_filename,
                "message": "Only .docx uploads are supported.",
            },
        )

    if not content:
        raise AdminIngestionError(
            message="Uploaded DOCX file is empty.",
            status_code=400,
            summary={
                "status": "failed",
                "filename": safe_filename,
                "message": "Uploaded DOCX file is empty.",
            },
        )

    if len(content) > MAX_DOCX_UPLOAD_BYTES:
        raise AdminIngestionError(
            message="Uploaded DOCX file exceeds the configured size limit.",
            status_code=413,
            summary={
                "status": "failed",
                "filename": safe_filename,
                "message": "Uploaded DOCX file exceeds the configured size limit.",
            },
        )

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type not in DOCX_MIME_TYPES:
        raise AdminIngestionError(
            message="Uploaded file MIME type is not allowed for DOCX ingestion.",
            status_code=400,
            summary={
                "status": "failed",
                "filename": safe_filename,
                "message": "Uploaded file MIME type is not allowed for DOCX ingestion.",
            },
        )

    return safe_filename


def _version_upload_path(document_id: int, version_id: int, filename: str) -> Path:
    destination_dir = UPLOAD_ROOT / str(document_id) / str(version_id)
    destination_dir.mkdir(parents=True, exist_ok=True)
    return destination_dir / filename


def _store_version_upload(
    *,
    document_id: int,
    version_id: int,
    filename: str,
    content: bytes,
) -> Path:
    destination = _version_upload_path(document_id, version_id, filename)
    if destination.exists():
        raise FileExistsError("A stored file already exists for this document version.")

    destination.write_bytes(content)
    return destination


def _safe_unlink_upload(path: Path | None) -> None:
    if path is None:
        return

    try:
        root = UPLOAD_ROOT.resolve()
        resolved = path.resolve()
        if root not in (resolved, *resolved.parents):
            return
        if resolved.is_file():
            resolved.unlink()
    except Exception:
        logging.getLogger(__name__).warning("failed_upload_cleanup_failed")


def _change_notes(
    *,
    change_reason: str | None,
    change_summary: str | None,
    effective_at: str | None,
) -> str:
    return json.dumps(
        {
            "change_reason": (change_reason or "").strip() or None,
            "change_summary": (change_summary or "").strip() or None,
            "effective_at": (effective_at or "").strip() or None,
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _change_note_value(version: DocumentVersion, key: str) -> str | None:
    notes = version.change_notes or ""
    try:
        parsed = json.loads(notes)
    except (TypeError, ValueError):
        parsed = {}

    if isinstance(parsed, dict):
        value = parsed.get(key)
        return str(value) if value not in (None, "") else None
    return None


def _record_audit_event(
    db: Session,
    *,
    action: str,
    user_id: int | None,
    document: SourceDocument | None,
    version_id: int | None = None,
    job_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    safe_metadata = dict(metadata or {})
    if version_id is not None:
        safe_metadata["document_version_id"] = version_id
    if job_id is not None:
        safe_metadata["ingestion_job_id"] = job_id

    db.add(
        AuditLog(
            user_id=user_id,
            department_id=document.department_id if document else None,
            action=action,
            entity_type="source_document",
            entity_id=document.document_id if document else None,
            method_json=safe_metadata,
        )
    )


def _get_or_create_department(db: Session) -> Department:
    department = db.query(Department).filter_by(code=DEFAULT_DEPARTMENT_CODE).first()

    if department:
        return department

    department = Department(
        name=DEFAULT_DEPARTMENT_NAME,
        code=DEFAULT_DEPARTMENT_CODE,
    )
    db.add(department)
    db.flush()

    return department


def _get_or_create_kb(db: Session, department: Department) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter_by(
        department_id=department.department_id,
        name=DEFAULT_KB_NAME,
    ).first()

    if kb:
        return kb

    kb = KnowledgeBase(
        department_id=department.department_id,
        name=DEFAULT_KB_NAME,
        description=DEFAULT_KB_DESCRIPTION,
        version="1.0",
        status="active",
    )
    db.add(kb)
    db.flush()

    return kb


def _checksum_exists(db: Session, checksum: str) -> bool:
    if not checksum:
        return False

    return db.query(SourceDocument).filter(
        SourceDocument.checksum == checksum,
        SourceDocument.processing_status == "completed",
    ).first() is not None


def _kb_code_exists(db: Session, kb_code: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT c.chunk_id
            FROM chunks c
            WHERE c.metadata_json->>'kb_code' = :kb_code
            LIMIT 1
            """
        ),
        {"kb_code": kb_code},
    ).first()

    return row is not None


def _record_terminal_job(
    *,
    filename: str,
    file_type: str,
    source_path: str | None,
    checksum: str | None,
    status: str,
    error_message: str,
    kb_code: str | None = None,
    article_title: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    now = utc_now()

    try:
        department = _get_or_create_department(db)
        kb = _get_or_create_kb(db, department)

        document = SourceDocument(
            kb_id=kb.kb_id,
            department_id=department.department_id,
            file_name=filename,
            file_type=file_type,
            source_path=source_path,
            checksum=checksum,
            processing_status=status,
        )
        db.add(document)
        db.flush()

        job = IngestionJob(
            document_id=document.document_id,
            version_id=None,
            job_type="docx_upload",
            status=status,
            started_at=now,
            completed_at=now,
            error_message=error_message,
            chunks_created=0,
            embeddings_created=0,
            config_json={
                "filename": filename,
                "source_path": source_path,
                "checksum": checksum,
                "kb_code": kb_code,
                "article_title": article_title,
                "warnings": warnings or [],
            },
        )
        db.add(job)
        db.flush()
        db.commit()

        return {
            "job_id": job.job_id,
            "status": job.status,
            "filename": filename,
            "kb_code": kb_code,
            "article_title": article_title,
            "document_id": document.document_id,
            "version_id": None,
            "chunks_created": 0,
            "embeddings_created": 0,
            "milvus_vectors_inserted": 0,
            "message": error_message,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _raise_with_recorded_job(
    *,
    filename: str,
    file_type: str,
    source_path: str | None,
    checksum: str | None,
    status: str,
    message: str,
    status_code: int,
    kb_code: str | None = None,
    article_title: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    try:
        summary = _record_terminal_job(
            filename=filename,
            file_type=file_type,
            source_path=source_path,
            checksum=checksum,
            status=status,
            error_message=message,
            kb_code=kb_code,
            article_title=article_title,
            warnings=warnings,
        )
    except Exception as record_error:
        summary = {
            "job_id": 0,
            "status": status,
            "filename": filename,
            "kb_code": kb_code,
            "article_title": article_title,
            "document_id": None,
            "version_id": None,
            "chunks_created": 0,
            "embeddings_created": 0,
            "milvus_vectors_inserted": 0,
            "message": f"{message} Failed to record ingestion job: {record_error}",
        }

    raise AdminIngestionError(
        message=message,
        status_code=status_code,
        summary=summary,
    )


def _prepare_chunks(article: dict[str, Any], version_number: int) -> list[dict[str, Any]]:
    chunks = smart_chunk_article(article)
    kb_code = str(article["kb_code"]).strip()

    for index, chunk in enumerate(chunks, start=1):
        external_chunk_id = f"{kb_code}::v{version_number}::{index:04d}"
        chunk["external_chunk_id"] = external_chunk_id
        chunk["chunk_index"] = index
        chunk["version_number"] = version_number
        chunk["source_filename"] = article["file_name"]

        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        metadata.update(
            {
                "external_chunk_id": external_chunk_id,
                "version_number": version_number,
                "source_filename": article["file_name"],
            }
        )
        chunk["metadata"] = metadata

    return chunks


@lru_cache(maxsize=1)
def _get_embedding_model() -> EmbeddingModel:
    return EmbeddingModel(EmbeddingConfig())


def _build_embedding_records(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], EmbeddingModel]:
    model = _get_embedding_model()
    records: list[dict[str, Any]] = []
    batch_size = max(1, model.config.batch_size)

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        embedding_texts = [build_embedding_text(chunk) for chunk in batch]
        vectors = model.encode(embedding_texts)

        for chunk, embedding_text, vector in zip(batch, embedding_texts, vectors, strict=True):
            metadata = build_metadata(
                chunk=chunk,
                embedding_text_hash=stable_hash(embedding_text),
                model_name=model.config.model_name,
            )

            records.append(
                {
                    "id": str(chunk["external_chunk_id"]),
                    "text": str(chunk["text"]).strip(),
                    "embedding_text": embedding_text,
                    "embedding": vector,
                    "metadata": metadata,
                }
            )

    return records, model


def _chunk_metadata(
    *,
    chunk: dict[str, Any],
    article: dict[str, Any],
    job: IngestionJob,
    document: SourceDocument,
    version: DocumentVersion,
) -> dict[str, Any]:
    return {
        "external_chunk_id": chunk["external_chunk_id"],
        "kb_code": article["kb_code"],
        "article_title": article["title"],
        "section_title": chunk.get("section_title"),
        "section_type": chunk.get("section_type"),
        "chunk_type": chunk.get("chunk_type"),
        "priority": chunk.get("priority"),
        "source_filename": article["file_name"],
        "file_name": article["file_name"],
        "source_path": article.get("source_path"),
        "checksum": article.get("checksum"),
        "version_number": version.version_number,
        "ingestion_job_id": job.job_id,
        "document_id": document.document_id,
        "version_id": version.version_id,
        "metadata": chunk.get("metadata", {}),
    }


def _attach_database_metadata(
    *,
    records: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    chunk_rows: list[Chunk],
    job: IngestionJob,
    document: SourceDocument,
    version: DocumentVersion,
) -> None:
    for record, chunk, chunk_row in zip(records, chunks, chunk_rows, strict=True):
        metadata = record.get("metadata") or {}
        metadata.update(
            {
                "source_filename": chunk.get("source_filename"),
                "source_path": chunk.get("source_path"),
                "version_number": version.version_number,
                "document_id": document.document_id,
                "version_id": version.version_id,
                "chunk_id": chunk_row.chunk_id,
                "ingestion_job_id": job.job_id,
                "milvus_collection": MILVUS_COLLECTION,
            }
        )
        record["metadata"] = metadata


def _preflight_duplicates(
    *,
    filename: str,
    source_path: Path,
    checksum: str,
    article: dict[str, Any],
    warnings: list[str],
) -> None:
    db = SessionLocal()

    try:
        if _checksum_exists(db, checksum):
            _raise_with_recorded_job(
                filename=filename,
                file_type="docx",
                source_path=str(source_path),
                checksum=checksum,
                status="duplicate",
                status_code=400,
                kb_code=article.get("kb_code"),
                article_title=article.get("title"),
                warnings=warnings,
                message="Duplicate document checksum detected. This upload was not ingested.",
            )

        if _kb_code_exists(db, str(article["kb_code"])):
            _raise_with_recorded_job(
                filename=filename,
                file_type="docx",
                source_path=str(source_path),
                checksum=checksum,
                status="duplicate",
                status_code=400,
                kb_code=article.get("kb_code"),
                article_title=article.get("title"),
                warnings=warnings,
                message="Duplicate KB code detected. Versioned replacement is not supported in this MVP.",
            )

    finally:
        db.close()


def ingest_docx_bytes(filename: str | None, content: bytes) -> dict[str, Any]:
    safe_filename = _safe_filename(filename)
    suffix = Path(safe_filename).suffix.lower()
    checksum = _checksum(content)

    if suffix != ".docx":
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type=suffix.lstrip(".") or "unknown",
            source_path=None,
            checksum=checksum,
            status="failed",
            status_code=400,
            message="Only .docx uploads are supported for this MVP.",
        )

    if not content:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=None,
            checksum=checksum,
            status="failed",
            status_code=400,
            message="Uploaded DOCX file is empty.",
        )

    upload_path = _store_upload(safe_filename, content, checksum)

    try:
        article = build_article(upload_path)
        article["file_name"] = safe_filename
        article["source_path"] = str(upload_path)
        article["checksum"] = checksum
        warnings = validate_article(article)
    except Exception as error:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status="failed",
            status_code=400,
            message=f"DOCX parsing failed: {error}",
        )

    fatal_warnings = sorted(FATAL_VALIDATION_WARNINGS.intersection(warnings))
    if fatal_warnings:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status="failed",
            status_code=400,
            kb_code=article.get("kb_code"),
            article_title=article.get("title"),
            warnings=warnings,
            message=f"DOCX validation failed: {', '.join(fatal_warnings)}",
        )

    _preflight_duplicates(
        filename=safe_filename,
        source_path=upload_path,
        checksum=checksum,
        article=article,
        warnings=warnings,
    )

    version_number = 1

    try:
        chunks = _prepare_chunks(article, version_number=version_number)
    except Exception as error:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status="failed",
            status_code=500,
            kb_code=article.get("kb_code"),
            article_title=article.get("title"),
            warnings=warnings,
            message=f"DOCX chunking failed: {error}",
        )

    if not chunks:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status="failed",
            status_code=400,
            kb_code=article.get("kb_code"),
            article_title=article.get("title"),
            warnings=warnings,
            message="DOCX article produced no searchable chunks.",
        )

    try:
        embedded_records, embedding_model = _build_embedding_records(chunks)
    except Exception as error:
        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status="failed",
            status_code=500,
            kb_code=article.get("kb_code"),
            article_title=article.get("title"),
            warnings=warnings,
            message=f"Embedding generation failed: {error}",
        )

    inserted_vector_ids: list[str] = []
    db = SessionLocal()

    try:
        if _checksum_exists(db, checksum):
            raise ValueError("Duplicate document checksum detected. This upload was not ingested.")

        if _kb_code_exists(db, str(article["kb_code"])):
            raise ValueError("Duplicate KB code detected. Versioned replacement is not supported in this MVP.")

        department = _get_or_create_department(db)
        kb = _get_or_create_kb(db, department)

        document = SourceDocument(
            kb_id=kb.kb_id,
            department_id=department.department_id,
            file_name=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            processing_status="processing",
        )
        db.add(document)
        db.flush()

        version = DocumentVersion(
            document_id=document.document_id,
            version_number=version_number,
            checksum=checksum,
            storage_path=str(upload_path),
            file_size_bytes=len(content),
            change_notes="Admin DOCX upload MVP ingestion.",
            processing_status="processing",
            is_current=True,
        )
        db.add(version)
        db.flush()
        document.current_version_id = version.version_id

        sheet = DocumentSheet(
            document_id=document.document_id,
            version_id=version.version_id,
            sheet_name="Document",
            sheet_index=0,
            description="Default sheet representation for uploaded DOCX article.",
        )
        db.add(sheet)
        db.flush()

        job = IngestionJob(
            document_id=document.document_id,
            version_id=version.version_id,
            job_type="docx_upload",
            status="processing",
            started_at=utc_now(),
            chunks_created=0,
            embeddings_created=0,
            config_json={
                "filename": safe_filename,
                "source_path": str(upload_path),
                "checksum": checksum,
                "kb_code": article.get("kb_code"),
                "article_title": article.get("title"),
                "warnings": warnings,
                "external_chunk_id_format": "{kb_code}::v{version_number}::{index:04d}",
                "search_visibility": {
                    "semantic": "available after Milvus insert",
                    "keyword": "existing file-backed keyword index is not refreshed in this MVP",
                },
            },
        )
        db.add(job)
        db.flush()

        chunk_rows: list[Chunk] = []
        for chunk in chunks:
            chunk_row = Chunk(
                sheet_id=sheet.sheet_id,
                version_id=version.version_id,
                job_id=job.job_id,
                chunk_text=chunk["text"],
                chunk_index=int(chunk["chunk_index"]),
                token_count=chunk.get("word_count"),
                chunk_type=chunk.get("chunk_type"),
                metadata_json=_chunk_metadata(
                    chunk=chunk,
                    article=article,
                    job=job,
                    document=document,
                    version=version,
                ),
            )
            db.add(chunk_row)
            chunk_rows.append(chunk_row)

        db.flush()

        _attach_database_metadata(
            records=embedded_records,
            chunks=chunks,
            chunk_rows=chunk_rows,
            job=job,
            document=document,
            version=version,
        )

        milvus_vectors_inserted = insert_embedding_records(
            embedded_records,
            dimension=embedding_model.dimension,
        )
        inserted_vector_ids = [record["id"] for record in embedded_records]

        if milvus_vectors_inserted != len(embedded_records):
            raise RuntimeError(
                f"Milvus insert count mismatch: expected {len(embedded_records)}, "
                f"inserted {milvus_vectors_inserted}"
            )

        for chunk_row, record in zip(chunk_rows, embedded_records, strict=True):
            embedding = Embedding(
                chunk_id=chunk_row.chunk_id,
                version_id=version.version_id,
                job_id=job.job_id,
                milvus_collection=MILVUS_COLLECTION,
                milvus_vector_id=record["id"],
                embedding_model=embedding_model.config.model_name,
                embedding_dimension=embedding_model.dimension,
            )
            db.add(embedding)

        job.status = "completed"
        job.completed_at = utc_now()
        job.chunks_created = len(chunks)
        job.embeddings_created = len(embedded_records)
        job.error_message = None
        document.processing_status = "completed"
        version.processing_status = "completed"

        db.commit()

        try:
            from app.services.retrieval_service import get_collection

            get_collection.cache_clear()
        except Exception:
            pass

        try:
            advance_knowledge_generation()
        except Exception:
            logging.getLogger(__name__).warning("cache_generation_advance_failed")

        return {
            "job_id": job.job_id,
            "status": job.status,
            "filename": safe_filename,
            "kb_code": article.get("kb_code"),
            "article_title": article.get("title"),
            "document_id": document.document_id,
            "version_id": version.version_id,
            "chunks_created": len(chunks),
            "embeddings_created": len(embedded_records),
            "milvus_vectors_inserted": milvus_vectors_inserted,
            "message": "DOCX article ingested successfully.",
        }

    except Exception as error:
        db.rollback()

        if inserted_vector_ids:
            try:
                delete_vectors(inserted_vector_ids, dimension=embedding_model.dimension)
            except Exception as cleanup_error:
                error = RuntimeError(f"{error}; Milvus cleanup failed: {cleanup_error}")

        status = "duplicate" if "Duplicate" in str(error) else "failed"
        status_code = 400 if status == "duplicate" or isinstance(error, ValueError) else 500

        _raise_with_recorded_job(
            filename=safe_filename,
            file_type="docx",
            source_path=str(upload_path),
            checksum=checksum,
            status=status,
            status_code=status_code,
            kb_code=article.get("kb_code"),
            article_title=article.get("title"),
            warnings=warnings,
            message=str(error),
        )

    finally:
        db.close()


def _next_version_number(db: Session, document_id: int) -> int:
    current_max = db.query(func.max(DocumentVersion.version_number)).filter(
        DocumentVersion.document_id == document_id,
    ).scalar()
    return int(current_max or 0) + 1


def _version_job(db: Session, version_id: int) -> IngestionJob | None:
    return db.query(IngestionJob).filter(
        IngestionJob.version_id == version_id,
    ).order_by(
        IngestionJob.created_at.desc(),
        IngestionJob.job_id.desc(),
    ).first()


def _version_filename(
    *,
    document: SourceDocument,
    version: DocumentVersion,
    config: dict[str, Any],
) -> str:
    value = config.get("filename")
    if not value and version.storage_path:
        value = Path(str(version.storage_path).replace("\\", "/")).name
    return _safe_filename(str(value or document.file_name))


def list_document_versions(source_document_id: int) -> list[dict[str, Any]] | None:
    db = SessionLocal()

    try:
        document = db.query(SourceDocument).filter(
            SourceDocument.document_id == source_document_id,
        ).first()
        if document is None:
            return None

        versions = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == source_document_id,
        ).order_by(
            DocumentVersion.version_number.desc(),
            DocumentVersion.version_id.desc(),
        ).all()

        items: list[dict[str, Any]] = []
        for version in versions:
            job = _version_job(db, version.version_id)
            config = _job_config(job) if job else {}
            items.append(
                {
                    "source_document_id": document.document_id,
                    "document_version_id": version.version_id,
                    "version_number": version.version_number,
                    "status": version.processing_status,
                    "is_current": bool(version.is_current),
                    "filename": _version_filename(
                        document=document,
                        version=version,
                        config=config,
                    ),
                    "uploaded_by": version.uploaded_by,
                    "uploaded_at": version.uploaded_at,
                    "activated_at": job.completed_at if job and version.is_current else None,
                    "superseded_at": None,
                    "change_reason": _change_note_value(version, "change_reason"),
                    "change_summary": _change_note_value(version, "change_summary"),
                    "effective_at": _change_note_value(version, "effective_at"),
                    "ingestion_job_id": job.job_id if job else None,
                    "ingestion_status": job.status if job else version.processing_status,
                    "chunks_created": job.chunks_created or 0 if job else 0,
                    "embeddings_created": job.embeddings_created or 0 if job else 0,
                    "error_message": job.error_message if job else None,
                }
            )

        return items

    finally:
        db.close()


def ingest_document_version_bytes(
    *,
    source_document_id: int,
    filename: str | None,
    content: bytes,
    uploaded_by_user_id: int | None,
    content_type: str | None = None,
    change_reason: str | None = None,
    change_summary: str | None = None,
    effective_at: str | None = None,
) -> dict[str, Any]:
    safe_filename = _validate_docx_upload(
        filename=filename,
        content=content,
        content_type=content_type,
    )
    checksum = _checksum(content)
    upload_path: Path | None = None
    inserted_vector_ids: list[str] = []
    vector_dimension: int | None = None
    db = SessionLocal()

    try:
        document = db.query(SourceDocument).filter(
            SourceDocument.document_id == source_document_id,
        ).with_for_update().first()
        if document is None:
            raise AdminIngestionError(
                message="Document not found.",
                status_code=404,
                summary={
                    "status": "failed",
                    "filename": safe_filename,
                    "message": "Document not found.",
                },
            )

        previous_version_id = document.current_version_id
        version_number = _next_version_number(db, document.document_id)
        version = DocumentVersion(
            document_id=document.document_id,
            version_number=version_number,
            uploaded_by=uploaded_by_user_id,
            checksum=checksum,
            storage_path=None,
            file_size_bytes=len(content),
            change_notes=_change_notes(
                change_reason=change_reason,
                change_summary=change_summary,
                effective_at=effective_at,
            ),
            processing_status="processing",
            is_current=False,
        )
        db.add(version)
        db.flush()

        upload_path = _store_version_upload(
            document_id=document.document_id,
            version_id=version.version_id,
            filename=safe_filename,
            content=content,
        )
        version.storage_path = str(upload_path)

        job = IngestionJob(
            document_id=document.document_id,
            version_id=version.version_id,
            job_type="docx_version_update",
            status="processing",
            triggered_by_fk=uploaded_by_user_id,
            started_at=utc_now(),
            chunks_created=0,
            embeddings_created=0,
            config_json={
                "filename": safe_filename,
                "checksum": checksum,
                "kb_code": None,
                "article_title": None,
                "previous_document_version_id": previous_version_id,
                "change_reason": (change_reason or "").strip() or None,
                "change_summary": (change_summary or "").strip() or None,
                "effective_at": (effective_at or "").strip() or None,
                "external_chunk_id_format": "{kb_code}::v{version_number}::{index:04d}",
                "activation": "previous version remains current until indexing succeeds",
            },
        )
        db.add(job)
        _record_audit_event(
            db,
            action="knowledge_article_update_started",
            user_id=uploaded_by_user_id,
            document=document,
            version_id=version.version_id,
            job_id=None,
            metadata={"previous_document_version_id": previous_version_id},
        )
        db.commit()

        article = build_article(upload_path)
        article["file_name"] = safe_filename
        article["source_path"] = str(upload_path)
        article["checksum"] = checksum
        warnings = validate_article(article)
        fatal_warnings = sorted(FATAL_VALIDATION_WARNINGS.intersection(warnings))
        if fatal_warnings:
            raise ValueError(f"DOCX validation failed: {', '.join(fatal_warnings)}")

        chunks = _prepare_chunks(article, version_number=version_number)
        if not chunks:
            raise ValueError("DOCX article produced no searchable chunks.")

        embedded_records, embedding_model = _build_embedding_records(chunks)
        vector_dimension = embedding_model.dimension

        document = db.query(SourceDocument).filter(
            SourceDocument.document_id == source_document_id,
        ).with_for_update().first()
        version = db.query(DocumentVersion).filter(
            DocumentVersion.version_id == version.version_id,
            DocumentVersion.document_id == source_document_id,
        ).first()
        job = db.query(IngestionJob).filter(
            IngestionJob.version_id == version.version_id,
            IngestionJob.job_type == "docx_version_update",
        ).order_by(IngestionJob.job_id.desc()).first()
        if document is None or version is None or job is None:
            raise RuntimeError("Version update state could not be reloaded.")

        sheet = DocumentSheet(
            document_id=document.document_id,
            version_id=version.version_id,
            sheet_name="Document",
            sheet_index=0,
            description="Default sheet representation for uploaded DOCX article revision.",
        )
        db.add(sheet)
        db.flush()

        chunk_rows: list[Chunk] = []
        for chunk in chunks:
            chunk_row = Chunk(
                sheet_id=sheet.sheet_id,
                version_id=version.version_id,
                job_id=job.job_id,
                chunk_text=chunk["text"],
                chunk_index=int(chunk["chunk_index"]),
                token_count=chunk.get("word_count"),
                chunk_type=chunk.get("chunk_type"),
                metadata_json=_chunk_metadata(
                    chunk=chunk,
                    article=article,
                    job=job,
                    document=document,
                    version=version,
                ),
            )
            db.add(chunk_row)
            chunk_rows.append(chunk_row)

        db.flush()
        _attach_database_metadata(
            records=embedded_records,
            chunks=chunks,
            chunk_rows=chunk_rows,
            job=job,
            document=document,
            version=version,
        )

        milvus_vectors_inserted = insert_embedding_records(
            embedded_records,
            dimension=embedding_model.dimension,
        )
        inserted_vector_ids = [record["id"] for record in embedded_records]
        if milvus_vectors_inserted != len(embedded_records):
            raise RuntimeError(
                f"Milvus insert count mismatch: expected {len(embedded_records)}, "
                f"inserted {milvus_vectors_inserted}"
            )

        for chunk_row, record in zip(chunk_rows, embedded_records, strict=True):
            db.add(
                Embedding(
                    chunk_id=chunk_row.chunk_id,
                    version_id=version.version_id,
                    job_id=job.job_id,
                    milvus_collection=MILVUS_COLLECTION,
                    milvus_vector_id=record["id"],
                    embedding_model=embedding_model.config.model_name,
                    embedding_dimension=embedding_model.dimension,
                )
            )

        for historical in db.query(DocumentVersion).filter(
            DocumentVersion.document_id == document.document_id,
            DocumentVersion.version_id != version.version_id,
        ).all():
            historical.is_current = False
            if historical.processing_status == "completed":
                historical.processing_status = "superseded"

        version.is_current = True
        version.processing_status = "completed"
        document.current_version_id = version.version_id
        document.file_name = safe_filename
        document.source_path = str(upload_path)
        document.checksum = checksum
        document.processing_status = "completed"
        job.status = "completed"
        job.completed_at = utc_now()
        job.error_message = None
        job.chunks_created = len(chunks)
        job.embeddings_created = len(embedded_records)
        job.config_json = {
            **(_job_config(job)),
            "kb_code": article.get("kb_code"),
            "article_title": article.get("title"),
            "warnings": warnings,
        }
        _record_audit_event(
            db,
            action="knowledge_article_update_completed",
            user_id=uploaded_by_user_id,
            document=document,
            version_id=version.version_id,
            job_id=job.job_id,
            metadata={
                "previous_document_version_id": previous_version_id,
                "status": "completed",
            },
        )
        db.commit()

        try:
            from app.services.retrieval_service import get_collection

            get_collection.cache_clear()
        except Exception:
            pass

        try:
            advance_knowledge_generation()
        except Exception:
            logging.getLogger(__name__).warning("cache_generation_advance_failed")

        return {
            "source_document_id": document.document_id,
            "document_version_id": version.version_id,
            "ingestion_job_id": job.job_id,
            "status": job.status,
            "filename": safe_filename,
            "kb_code": article.get("kb_code"),
            "article_title": article.get("title"),
            "version_number": version.version_number,
            "chunks_created": len(chunks),
            "embeddings_created": len(embedded_records),
            "milvus_vectors_inserted": milvus_vectors_inserted,
            "message": "DOCX article version ingested and activated successfully.",
        }

    except AdminIngestionError:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()
        if inserted_vector_ids and vector_dimension is not None:
            try:
                delete_vectors(inserted_vector_ids, dimension=vector_dimension)
            except Exception as cleanup_error:
                logging.getLogger(__name__).warning(
                    "milvus_version_update_cleanup_failed: %s", cleanup_error
                )

        try:
            version_id = locals().get("version").version_id if locals().get("version") else None
            job_id = locals().get("job").job_id if locals().get("job") else None
            document = db.query(SourceDocument).filter(
                SourceDocument.document_id == source_document_id,
            ).first()
            version = db.query(DocumentVersion).filter(
                DocumentVersion.version_id == version_id,
            ).first() if version_id else None
            job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first() if job_id else None
            if version is not None:
                version.processing_status = "failed"
                version.is_current = False
                version.storage_path = None
            if job is not None:
                job.status = "failed"
                job.completed_at = utc_now()
                job.error_message = "Document version update failed."
            _record_audit_event(
                db,
                action="knowledge_article_update_failed",
                user_id=uploaded_by_user_id,
                document=document,
                version_id=version_id,
                job_id=job_id,
                metadata={"status": "failed"},
            )
            db.commit()
        except Exception:
            db.rollback()

        _safe_unlink_upload(upload_path)
        status_code = 400 if isinstance(error, ValueError) else 500
        raise AdminIngestionError(
            message="Document version update failed.",
            status_code=status_code,
            summary={
                "source_document_id": source_document_id,
                "document_version_id": locals().get("version").version_id if locals().get("version") else None,
                "ingestion_job_id": locals().get("job").job_id if locals().get("job") else None,
                "status": "failed",
                "filename": safe_filename,
                "message": "Document version update failed.",
            },
        ) from None

    finally:
        db.close()


def _job_config(job: IngestionJob) -> dict[str, Any]:
    return job.config_json if isinstance(job.config_json, dict) else {}


def _job_updated_at(job: IngestionJob) -> datetime | None:
    return job.completed_at or job.started_at or job.created_at


def _job_to_list_item(job: IngestionJob, document: SourceDocument | None) -> dict[str, Any]:
    completed = job.status == "completed"

    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "source_path": document.source_path if document else None,
        "filename": document.file_name if document else None,
        "created_at": job.created_at,
        "updated_at": _job_updated_at(job),
        "processed_documents": 1 if completed else 0,
        "processed_chunks": job.chunks_created or 0,
        "error_message": job.error_message,
    }


def list_ingestion_jobs(limit: int = 20) -> list[dict[str, Any]]:
    db = SessionLocal()

    try:
        rows = db.query(IngestionJob, SourceDocument).outerjoin(
            SourceDocument,
            IngestionJob.document_id == SourceDocument.document_id,
        ).order_by(
            IngestionJob.created_at.desc(),
            IngestionJob.job_id.desc(),
        ).limit(limit).all()

        return [_job_to_list_item(job, document) for job, document in rows]

    finally:
        db.close()


def get_ingestion_job_detail(job_id: int) -> dict[str, Any] | None:
    db = SessionLocal()

    try:
        row = db.query(IngestionJob, SourceDocument).outerjoin(
            SourceDocument,
            IngestionJob.document_id == SourceDocument.document_id,
        ).filter(IngestionJob.job_id == job_id).first()

        if not row:
            return None

        job, document = row
        config = _job_config(job)
        detail = _job_to_list_item(job, document)
        detail.update(
            {
                "document_id": job.document_id,
                "version_id": job.version_id,
                "kb_code": config.get("kb_code"),
                "article_title": config.get("article_title"),
                "chunks_created": job.chunks_created or 0,
                "embeddings_created": job.embeddings_created or 0,
                "config_json": config,
            }
        )

        return detail

    finally:
        db.close()
