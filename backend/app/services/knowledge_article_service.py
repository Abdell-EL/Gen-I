from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Chunk, DocumentVersion, SourceDocument, User


class ArticleNotFoundError(LookupError):
    pass


class OriginalDocumentNotFoundError(LookupError):
    pass


DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _normalize_role(role: object) -> str:
    return str(role or "").strip().lower()


def can_read_document(user: User, _document: SourceDocument) -> bool:
    return _normalize_role(getattr(user, "role", None)) in {"admin", "agent"}


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _source_external_id(item: dict[str, Any]) -> str | None:
    value = item.get("id") or item.get("external_chunk_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _item_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata_dict(item.get("metadata"))
    nested = _metadata_dict(metadata.get("metadata"))
    if nested:
        merged = dict(nested)
        merged.update(metadata)
        return merged
    return metadata


def attach_source_database_metadata(retrieved_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = [dict(item) for item in retrieved_chunks]
    external_ids = [external_id for item in enriched if (external_id := _source_external_id(item))]
    if not external_ids:
        return enriched

    for item in enriched:
        metadata = _item_metadata(item)
        if metadata:
            item.setdefault("source_document_id", metadata.get("document_id"))
            item.setdefault("document_version_id", metadata.get("version_id"))
            item.setdefault("file_name", metadata.get("file_name") or metadata.get("source_filename"))

    db = SessionLocal()
    try:
        external_expr = Chunk.metadata_json["external_chunk_id"].as_string()
        rows = db.execute(
            select(Chunk, DocumentVersion, SourceDocument)
            .join(DocumentVersion, Chunk.version_id == DocumentVersion.version_id)
            .join(SourceDocument, DocumentVersion.document_id == SourceDocument.document_id)
            .where(external_expr.in_(external_ids))
        ).all()
    except Exception:
        return enriched
    finally:
        db.close()

    by_external_id = {}
    for chunk, version, document in rows:
        metadata = _metadata_dict(chunk.metadata_json)
        external_id = metadata.get("external_chunk_id")
        if external_id:
            by_external_id[str(external_id)] = {
                "chunk_id": chunk.chunk_id,
                "source_document_id": document.document_id,
                "document_version_id": version.version_id,
                "file_name": document.file_name,
                "kb_code": metadata.get("kb_code"),
                "article_title": metadata.get("article_title"),
                "section_title": metadata.get("section_title"),
            }

    for item in enriched:
        external_id = _source_external_id(item)
        database_values = by_external_id.get(external_id or "")
        if not database_values:
            continue
        for key, value in database_values.items():
            if value is not None:
                item[key] = value
    return enriched


def _select_version(db: Session, document: SourceDocument, version_id: int | None) -> DocumentVersion | None:
    if version_id is not None:
        return db.execute(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.document_id,
                DocumentVersion.version_id == version_id,
            )
        ).scalar_one_or_none()

    if document.current_version_id is not None:
        version = db.get(DocumentVersion, document.current_version_id)
        if version is not None and version.document_id == document.document_id:
            return version

    return db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.document_id)
        .order_by(DocumentVersion.is_current.desc(), DocumentVersion.version_number.desc())
    ).scalars().first()


def _article_sections(chunks: list[Chunk]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    by_title: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        metadata = _metadata_dict(chunk.metadata_json)
        title = str(metadata.get("section_title") or "Article").strip() or "Article"
        if title not in by_title:
            by_title[title] = {"title": title, "chunk_ids": [], "content": []}
            sections.append(by_title[title])
        by_title[title]["chunk_ids"].append(chunk.chunk_id)
        by_title[title]["content"].append(chunk.chunk_text)

    return [
        {
            "title": section["title"],
            "chunk_ids": section["chunk_ids"],
            "content": "\n\n".join(section["content"]).strip(),
        }
        for section in sections
    ]



def _safe_download_filename(filename: str | None) -> str:
    raw_name = Path(str(filename or "document.docx").replace("\\", "/")).name
    stem = Path(raw_name).stem
    clean_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
    if not clean_stem:
        clean_stem = "document"
    return f"{clean_stem}.docx"


def _allowed_document_roots() -> list[Path]:
    cwd = Path.cwd().resolve()
    roots = [cwd / "data"]
    upload_root = Path(os.getenv("KB_UPLOAD_ROOT", "data/uploads/kb_articles"))
    if not upload_root.is_absolute():
        upload_root = cwd / upload_root
    roots.append(upload_root)
    return [root.resolve() for root in roots]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_original_document_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None

    normalized = str(stored_path).replace("\\", "/")
    raw_path = Path(normalized)
    candidate = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path

    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None

    if not resolved.is_file() or resolved.suffix.lower() != ".docx":
        return None

    allowed_roots = _allowed_document_roots()
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        return None

    return resolved


def get_original_document_file(
    db: Session,
    *,
    source_document_id: int,
    current_user: User,
    version_id: int | None = None,
) -> dict[str, Any]:
    document = db.get(SourceDocument, source_document_id)
    if document is None or not can_read_document(current_user, document):
        raise OriginalDocumentNotFoundError("Document not found.")

    version = _select_version(db, document, version_id)
    if version is None:
        raise OriginalDocumentNotFoundError("Document not found.")

    stored_path = version.storage_path or document.source_path
    resolved_path = _resolve_original_document_path(stored_path)
    if resolved_path is None:
        raise OriginalDocumentNotFoundError("Document not found.")

    version_filename = Path(str(version.storage_path or resolved_path.name).replace("\\", "/")).name

    return {
        "path": resolved_path,
        "filename": _safe_download_filename(version_filename or document.file_name),
        "media_type": DOCX_MIME_TYPE,
        "document_version_id": version.version_id,
    }


def get_article_detail(
    db: Session,
    *,
    source_document_id: int,
    current_user: User,
    version_id: int | None = None,
    chunk_id: int | None = None,
) -> dict[str, Any]:
    document = db.get(SourceDocument, source_document_id)
    if document is None or not can_read_document(current_user, document):
        raise ArticleNotFoundError("Article not found.")

    version = _select_version(db, document, version_id)
    if version is None:
        raise ArticleNotFoundError("Article not found.")

    chunks = db.execute(
        select(Chunk)
        .where(Chunk.version_id == version.version_id)
        .order_by(Chunk.chunk_index.asc())
    ).scalars().all()

    requested_chunk = None
    if chunk_id is not None:
        requested = next((chunk for chunk in chunks if chunk.chunk_id == chunk_id), None)
        if requested is None:
            raise ArticleNotFoundError("Article not found.")
        metadata = _metadata_dict(requested.metadata_json)
        requested_chunk = {
            "chunk_id": requested.chunk_id,
            "chunk_index": requested.chunk_index,
            "section_title": metadata.get("section_title"),
        }

    first_metadata = _metadata_dict(chunks[0].metadata_json) if chunks else {}
    current_version_id = document.current_version_id
    sections = _article_sections(chunks)
    content = "\n\n".join(chunk.chunk_text for chunk in chunks).strip()

    return {
        "source_document_id": document.document_id,
        "document_version_id": version.version_id,
        "current_document_version_id": current_version_id,
        "is_current_version": current_version_id == version.version_id,
        "version_number": version.version_number,
        "title": first_metadata.get("article_title") or document.file_name,
        "kb_code": first_metadata.get("kb_code"),
        "filename": document.file_name,
        "content": content,
        "sections": sections,
        "created_at": document.created_at,
        "uploaded_at": version.uploaded_at,
        "updated_at": version.uploaded_at,
        "requested_chunk": requested_chunk,
    }
