from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import shutil
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.models import (
    AuditLog,
    Chunk,
    DocumentSheet,
    DocumentVersion,
    Embedding,
    IngestionJob,
    SourceDocument,
)
from app.routes import router
from app.services import admin_ingestion_service, retrieval_service


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class AdminDocumentVersionRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.upload_root = Path.cwd() / "data" / "test_version_uploads"
        shutil.rmtree(self.upload_root, ignore_errors=True)
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self._seed_document()

        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.admin = SimpleNamespace(user_id=9, role="admin", is_active=True, department_id=1)
        self.agent = SimpleNamespace(user_id=8, role="agent", is_active=True, department_id=1)
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

        self.patches = [
            patch.object(admin_ingestion_service, "SessionLocal", self.Session),
            patch.object(admin_ingestion_service, "UPLOAD_ROOT", self.upload_root),
            patch.object(
                admin_ingestion_service,
                "build_article",
                return_value={"kb_code": "KB-REV", "title": "Article revise"},
            ),
            patch.object(admin_ingestion_service, "validate_article", return_value=[]),
            patch.object(admin_ingestion_service, "_prepare_chunks", side_effect=self._chunks),
            patch.object(
                admin_ingestion_service,
                "_build_embedding_records",
                side_effect=self._embedding_records,
            ),
            patch.object(admin_ingestion_service, "insert_embedding_records", return_value=1),
            patch.object(admin_ingestion_service, "delete_vectors"),
            patch.object(admin_ingestion_service, "advance_knowledge_generation"),
            patch.object(retrieval_service, "SessionLocal", self.Session),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        shutil.rmtree(self.upload_root, ignore_errors=True)

    def _seed_document(self):
        old_path = self.upload_root / "1" / "1" / "old.docx"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(b"old-docx")
        document = SourceDocument(
            document_id=1,
            kb_id=1,
            department_id=1,
            file_name="old.docx",
            file_type="docx",
            source_path=str(old_path),
            checksum="old-checksum",
            current_version_id=1,
            processing_status="completed",
        )
        version = DocumentVersion(
            version_id=1,
            document_id=1,
            version_number=1,
            storage_path=str(old_path),
            checksum="old-checksum",
            processing_status="completed",
            is_current=True,
        )
        sheet = DocumentSheet(
            sheet_id=1,
            document_id=1,
            version_id=1,
            sheet_name="Document",
            sheet_index=0,
        )
        chunk = Chunk(
            chunk_id=1,
            sheet_id=1,
            version_id=1,
            chunk_text="Ancien contenu",
            chunk_index=1,
            chunk_type="procedure",
            metadata_json={"external_chunk_id": "KB-REV::v1::0001", "kb_code": "KB-REV"},
        )
        embedding = Embedding(
            chunk_id=1,
            version_id=1,
            job_id=None,
            milvus_collection="sogetrel_chunks",
            milvus_vector_id="KB-REV::v1::0001",
            embedding_model="test-model",
            embedding_dimension=3,
        )
        self.db.add_all([document, version, sheet, chunk, embedding])
        self.db.commit()

    def _chunks(self, article, version_number):
        return [
            {
                "external_chunk_id": f"KB-REV::v{version_number}::0001",
                "chunk_index": 1,
                "version_number": version_number,
                "text": "Nouveau contenu",
                "word_count": 2,
                "chunk_type": "procedure",
                "section_title": "Procedure",
                "priority": "high",
                "source_filename": article["file_name"],
                "source_path": article["source_path"],
                "metadata": {"kb_code": "KB-REV"},
            }
        ]

    def _embedding_records(self, chunks):
        model = SimpleNamespace(
            dimension=3,
            config=SimpleNamespace(model_name="test-model"),
        )
        return [
            {
                "id": chunks[0]["external_chunk_id"],
                "text": chunks[0]["text"],
                "embedding_text": chunks[0]["text"],
                "embedding": [0.1, 0.2, 0.3],
                "metadata": {"kb_code": "KB-REV"},
            }
        ], model

    def _upload(self, filename="revised.docx", content=b"PK revised bytes", content_type=DOCX_MIME):
        return self.client.post(
            "/api/v1/admin/knowledge/documents/1/versions",
            files={"file": (filename, content, content_type)},
            data={"change_reason": "process change", "change_summary": "Updated procedure"},
        )

    def test_admin_uploads_revised_version_successfully_and_activates_after_indexing(self):
        response = self._upload()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source_document_id"], 1)
        self.assertEqual(body["version_number"], 2)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["chunks_created"], 1)
        self.assertEqual(body["embeddings_created"], 1)

        self.db.expire_all()
        document = self.db.get(SourceDocument, 1)
        versions = self.db.query(DocumentVersion).filter_by(document_id=1).all()
        current_versions = [version for version in versions if version.is_current]
        self.assertEqual(document.current_version_id, body["document_version_id"])
        self.assertEqual(len(current_versions), 1)
        self.assertEqual(current_versions[0].version_number, 2)
        self.assertEqual(self.db.get(DocumentVersion, 1).processing_status, "superseded")
        self.assertEqual(self.db.query(Chunk).filter_by(version_id=body["document_version_id"]).count(), 1)
        self.assertEqual(self.db.query(Embedding).filter_by(version_id=body["document_version_id"]).count(), 1)
        audit_actions = {row.action for row in self.db.query(AuditLog).all()}
        self.assertIn("knowledge_article_update_started", audit_actions)
        self.assertIn("knowledge_article_update_completed", audit_actions)
        rendered = response.text
        self.assertNotIn(str(self.upload_root), rendered)
        self.assertNotIn("checksum", rendered.lower())

    def test_agent_cannot_upload_revised_version(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        response = self._upload()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.query(DocumentVersion).filter_by(document_id=1).count(), 1)

    def test_missing_document_and_invalid_uploads_return_safe_errors(self):
        missing = self.client.post(
            "/api/v1/admin/knowledge/documents/999/versions",
            files={"file": ("revised.docx", b"PK bytes", DOCX_MIME)},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn(str(self.upload_root), missing.text)

        invalid_extension = self.client.post(
            "/api/v1/admin/knowledge/documents/1/versions",
            files={"file": ("revised.pdf", b"PK bytes", "application/pdf")},
        )
        self.assertEqual(invalid_extension.status_code, 400)

        invalid_mime = self.client.post(
            "/api/v1/admin/knowledge/documents/1/versions",
            files={"file": ("revised.docx", b"PK bytes", "text/plain")},
        )
        self.assertEqual(invalid_mime.status_code, 400)

    def test_failure_before_activation_leaves_previous_version_current(self):
        with patch.object(admin_ingestion_service, "build_article", side_effect=RuntimeError("parse failed")):
            response = self._upload()
        self.assertEqual(response.status_code, 500)
        self.db.expire_all()
        document = self.db.get(SourceDocument, 1)
        self.assertEqual(document.current_version_id, 1)
        self.assertTrue(self.db.get(DocumentVersion, 1).is_current)
        failed_versions = self.db.query(DocumentVersion).filter_by(processing_status="failed").all()
        self.assertEqual(len(failed_versions), 1)
        self.assertFalse(failed_versions[0].is_current)
        self.assertIsNone(failed_versions[0].storage_path)
        audit_actions = {row.action for row in self.db.query(AuditLog).all()}
        self.assertIn("knowledge_article_update_failed", audit_actions)

    def test_version_history_is_safe_and_exact_version_download_works(self):
        upload = self._upload(filename="unsafe ../revised.docx", content=b"PK exact bytes")
        self.assertEqual(upload.status_code, 200, upload.text)
        version_id = upload.json()["document_version_id"]

        history = self.client.get("/api/v1/admin/knowledge/documents/1/versions")
        self.assertEqual(history.status_code, 200)
        items = history.json()
        self.assertEqual([item["version_number"] for item in items], [2, 1])
        self.assertEqual(items[0]["filename"], "revised.docx")
        self.assertEqual(items[1]["filename"], "old.docx")
        rendered = history.text
        self.assertNotIn(str(self.upload_root), rendered)
        self.assertNotIn("checksum", rendered.lower())
        self.assertEqual(items[0]["change_reason"], "process change")

        download = self.client.get(f"/api/v1/knowledge/documents/1/original?version_id={version_id}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"PK exact bytes")
        self.assertIn("revised.docx", download.headers["content-disposition"])

        old_download = self.client.get("/api/v1/knowledge/documents/1/original?version_id=1")
        self.assertEqual(old_download.status_code, 200)
        self.assertEqual(old_download.content, b"old-docx")
        self.assertIn("old.docx", old_download.headers["content-disposition"])

    def test_two_successful_updates_leave_exactly_one_current_version(self):
        first = self._upload(filename="first.docx", content=b"PK first")
        second = self._upload(filename="second.docx", content=b"PK second")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.db.expire_all()
        versions = self.db.query(DocumentVersion).filter_by(document_id=1).all()
        self.assertEqual([version.version_number for version in versions], [1, 2, 3])
        self.assertEqual(sum(1 for version in versions if version.is_current), 1)
        self.assertEqual(self.db.get(SourceDocument, 1).current_version_id, second.json()["document_version_id"])

    def test_retrieval_filters_superseded_version_hits(self):
        self._upload()
        self.db.expire_all()
        current_id = self.db.get(SourceDocument, 1).current_version_id
        hits = [
            {"rank": 1, "id": "old", "metadata": {"document_id": 1, "version_id": 1}},
            {"rank": 2, "id": "new", "metadata": {"document_id": 1, "version_id": current_id}},
            {"rank": 3, "id": "legacy", "metadata": {}},
        ]
        filtered = retrieval_service._filter_current_version_hits(hits)
        self.assertEqual([hit["id"] for hit in filtered], ["new", "legacy"])


if __name__ == "__main__":
    unittest.main()
