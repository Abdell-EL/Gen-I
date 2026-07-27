import json
from pathlib import Path
from datetime import datetime

from app.database import Base, engine, SessionLocal
from app.models import (
    Department,
    KnowledgeBase,
    SourceDocument,
    DocumentVersion,
    DocumentSheet,
    Chunk,
    IngestionJob,
)

BASE_DIR = Path(__file__).resolve().parents[1]
CHUNKS_PATH = BASE_DIR / "data" / "processed" / "chunks.json"

DEFAULT_DEPARTMENT_CODE = "FDE"
DEFAULT_DEPARTMENT_NAME = "FDE"
DEFAULT_KB_NAME = "Base de connaissance FDE"


def utc_now():
    return datetime.utcnow()


def parse_chunk_index(item):
    external_id = item.get("external_chunk_id")

    if external_id and "::" in external_id:
        last_part = external_id.split("::")[-1]
        if last_part.isdigit():
            return int(last_part)

    return item.get("chunk_index", 0)


def get_or_create_department(db):
    department = db.query(Department).filter_by(
        code=DEFAULT_DEPARTMENT_CODE
    ).first()

    if department:
        return department

    department = Department(
        name=DEFAULT_DEPARTMENT_NAME,
        code=DEFAULT_DEPARTMENT_CODE,
    )

    db.add(department)
    db.flush()

    return department


def get_or_create_kb(db, department):
    kb = db.query(KnowledgeBase).filter_by(
        department_id=department.department_id,
        name=DEFAULT_KB_NAME,
    ).first()

    if kb:
        return kb

    kb = KnowledgeBase(
        department_id=department.department_id,
        name=DEFAULT_KB_NAME,
        description="Knowledge base for FDE operational articles.",
        version="1.0",
        status="active",
    )

    db.add(kb)
    db.flush()

    return kb


def get_or_create_document(db, kb, department, item):
    document = db.query(SourceDocument).filter_by(
        kb_id=kb.kb_id,
        file_name=item["file_name"],
    ).first()

    if document:
        return document

    document = SourceDocument(
        kb_id=kb.kb_id,
        department_id=department.department_id,
        file_name=item["file_name"],
        file_type=item.get("file_type") or "docx",
        source_path=item.get("source_path"),
        checksum=item.get("checksum"),
        processing_status="completed",
    )

    db.add(document)
    db.flush()

    return document


def get_or_create_version(db, document, item):
    version = db.query(DocumentVersion).filter_by(
        document_id=document.document_id,
        version_number=1,
    ).first()

    if version:
        return version

    version = DocumentVersion(
        document_id=document.document_id,
        version_number=1,
        checksum=item.get("checksum"),
        storage_path=item.get("source_path"),
        processing_status="completed",
        is_current=True,
        change_notes="Initial ingestion from processed chunks.",
    )

    db.add(version)
    db.flush()

    document.current_version_id = version.version_id

    return version


def get_or_create_sheet(db, document, version):
    sheet = db.query(DocumentSheet).filter_by(
        document_id=document.document_id,
        version_id=version.version_id,
        sheet_name="Document",
    ).first()

    if sheet:
        return sheet

    sheet = DocumentSheet(
        document_id=document.document_id,
        version_id=version.version_id,
        sheet_name="Document",
        sheet_index=0,
        description="Default sheet representation for DOCX documents.",
    )

    db.add(sheet)
    db.flush()

    return sheet


def create_ingestion_job(db, document, version):
    job = IngestionJob(
        document_id=document.document_id,
        version_id=version.version_id,
        job_type="chunk_load",
        status="processing",
        started_at=utc_now(),
        chunks_created=0,
        config_json={
            "source": "chunks.json",
            "loader": "load_chunks_to_db.py",
        },
    )

    db.add(job)
    db.flush()

    return job


def chunk_exists(db, version, chunk_index):
    return db.query(Chunk).filter_by(
        version_id=version.version_id,
        chunk_index=chunk_index,
    ).first()


def build_chunk(item, sheet, version, job, chunk_index):
    return Chunk(
        sheet_id=sheet.sheet_id,
        version_id=version.version_id,
        job_id=job.job_id,
        chunk_text=item["text"],
        chunk_index=chunk_index,
        token_count=item.get("word_count"),
        chunk_type=item.get("chunk_type"),
        metadata_json={
            "external_chunk_id": item.get("external_chunk_id"),
            "kb_code": item.get("kb_code"),
            "article_title": item.get("article_title"),
            "file_name": item.get("file_name"),
            "section_title": item.get("section_title"),
            "section_type": item.get("section_type"),
            "priority": item.get("priority"),
            "source_path": item.get("source_path"),
            "checksum": item.get("checksum"),
            "metadata": item.get("metadata", {}),
        },
    )


def mark_jobs_completed(jobs):
    for job in jobs:
        job.status = "completed"
        job.completed_at = utc_now()


def mark_jobs_failed(jobs, error):
    for job in jobs:
        job.status = "failed"
        job.completed_at = utc_now()

        if hasattr(job, "error_message"):
            job.error_message = str(error)


def main():
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Missing file: {CHUNKS_PATH}")

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    document_cache = {}
    version_cache = {}
    sheet_cache = {}
    job_cache = {}

    inserted_chunks = 0
    skipped_chunks = 0

    try:
        with open(CHUNKS_PATH, "r", encoding="utf-8") as file:
            chunks = json.load(file)

        department = get_or_create_department(db)
        kb = get_or_create_kb(db, department)

        for item in chunks:
            file_name = item["file_name"]

            if file_name not in document_cache:
                document = get_or_create_document(db, kb, department, item)
                version = get_or_create_version(db, document, item)
                sheet = get_or_create_sheet(db, document, version)
                job = create_ingestion_job(db, document, version)

                document_cache[file_name] = document
                version_cache[file_name] = version
                sheet_cache[file_name] = sheet
                job_cache[file_name] = job

            version = version_cache[file_name]
            sheet = sheet_cache[file_name]
            job = job_cache[file_name]

            chunk_index = parse_chunk_index(item)

            existing_chunk = chunk_exists(db, version, chunk_index)

            if existing_chunk:
                skipped_chunks += 1
                continue

            chunk = build_chunk(
                item=item,
                sheet=sheet,
                version=version,
                job=job,
                chunk_index=chunk_index,
            )

            db.add(chunk)

            inserted_chunks += 1
            job.chunks_created += 1

        mark_jobs_completed(job_cache.values())

        db.commit()

        print("Load completed.")
        print(f"Documents processed: {len(document_cache)}")
        print(f"Inserted chunks: {inserted_chunks}")
        print(f"Skipped existing chunks: {skipped_chunks}")

    except Exception as exc:
        db.rollback()

        try:
            mark_jobs_failed(job_cache.values(), exc)
            db.commit()
        except Exception:
            db.rollback()

        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()