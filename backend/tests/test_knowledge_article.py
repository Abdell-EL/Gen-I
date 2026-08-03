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
from app.models import Chunk, DocumentSheet, DocumentVersion, SourceDocument
from app.routes import router


class KnowledgeArticleRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.original_dir = Path.cwd() / "data" / "test_original_docs"
        self.original_dir.mkdir(parents=True, exist_ok=True)
        self.old_file = self.original_dir / "old_original.docx"
        self.current_file = self.original_dir / "current_original.docx"
        self.old_file.write_bytes(b"old-docx-bytes")
        self.current_file.write_bytes(b"current-docx-bytes")
        self._seed_article()

        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.user = SimpleNamespace(user_id=42, role="agent", is_active=True, department_id=1)
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        shutil.rmtree(self.original_dir, ignore_errors=True)

    def _seed_article(self):
        document = SourceDocument(
            document_id=1,
            kb_id=1,
            department_id=1,
            file_name="unsafe article name.docx",
            file_type="docx",
            source_path="/internal/path/article.docx",
            checksum="secret-checksum",
            current_version_id=2,
            processing_status="completed",
        )
        old_version = DocumentVersion(
            version_id=1,
            document_id=1,
            version_number=1,
            storage_path="data\\test_original_docs\\old_original.docx",
            checksum="old-secret",
            is_current=False,
            processing_status="completed",
        )
        current_version = DocumentVersion(
            version_id=2,
            document_id=1,
            version_number=2,
            storage_path="data/test_original_docs/current_original.docx",
            checksum="new-secret",
            is_current=True,
            processing_status="completed",
        )
        old_sheet = DocumentSheet(sheet_id=1, document_id=1, version_id=1, sheet_name="Article")
        current_sheet = DocumentSheet(sheet_id=2, document_id=1, version_id=2, sheet_name="Article")
        old_chunk = Chunk(
            chunk_id=10,
            sheet_id=1,
            version_id=1,
            chunk_text="Ancien contenu cité.",
            chunk_index=0,
            chunk_type="text",
            metadata_json={
                "external_chunk_id": "old-ext",
                "article_title": "Article ancien",
                "kb_code": "KB-OLD",
                "section_title": "Ancienne section",
            },
        )
        current_chunk = Chunk(
            chunk_id=20,
            sheet_id=2,
            version_id=2,
            chunk_text="Contenu courant.",
            chunk_index=0,
            chunk_type="text",
            metadata_json={
                "external_chunk_id": "current-ext",
                "article_title": "Article courant",
                "kb_code": "KB-CUR",
                "section_title": "Section courante",
            },
        )
        other_document = SourceDocument(
            document_id=2,
            kb_id=1,
            department_id=1,
            file_name="other.docx",
            file_type="docx",
            source_path="data/test_original_docs/current_original.docx",
            current_version_id=99,
            processing_status="completed",
        )
        other_version = DocumentVersion(
            version_id=99,
            document_id=2,
            version_number=1,
            storage_path="data/test_original_docs/current_original.docx",
            is_current=True,
            processing_status="completed",
        )
        traversal_version = DocumentVersion(
            version_id=100,
            document_id=1,
            version_number=3,
            storage_path="data/../app/routes.py",
            is_current=False,
            processing_status="completed",
        )
        missing_version = DocumentVersion(
            version_id=101,
            document_id=1,
            version_number=4,
            storage_path="data/test_original_docs/missing.docx",
            is_current=False,
            processing_status="completed",
        )
        self.db.add_all([
            document, old_version, current_version, old_sheet, current_sheet, old_chunk,
            current_chunk, other_document, other_version, traversal_version, missing_version,
        ])
        self.db.commit()

    def test_accessible_original_docx_returns_file_with_safe_headers(self):
        response = self.client.get("/api/v1/knowledge/documents/1/original?version_id=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"old-docx-bytes")
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        disposition = response.headers["content-disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn("old_original.docx", disposition)
        self.assertNotIn("data/", disposition)
        self.assertNotIn("test_original_docs", disposition)

    def test_original_docx_defaults_to_current_version(self):
        response = self.client.get("/api/v1/knowledge/documents/1/original")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"current-docx-bytes")

    def test_original_docx_unauthenticated_request_is_rejected(self):
        del self.app.dependency_overrides[get_current_user]
        response = self.client.get("/api/v1/knowledge/documents/1/original")
        self.assertEqual(response.status_code, 401)

    def test_original_docx_inaccessible_document_is_hidden(self):
        with patch("app.services.knowledge_article_service.can_read_document", return_value=False):
            response = self.client.get("/api/v1/knowledge/documents/1/original")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Document not found."})

    def test_original_docx_missing_invalid_or_wrong_version_returns_safe_404(self):
        for path in (
            "/api/v1/knowledge/documents/999/original",
            "/api/v1/knowledge/documents/1/original?version_id=99",
            "/api/v1/knowledge/documents/1/original?version_id=101",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                rendered = response.text
                self.assertEqual(response.json(), {"detail": "Document not found."})
                self.assertNotIn("test_original_docs", rendered)
                self.assertNotIn("storage_path", rendered)

    def test_original_docx_stored_traversal_path_is_rejected(self):
        response = self.client.get("/api/v1/knowledge/documents/1/original?version_id=100")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Document not found."})

    def test_original_docx_route_contract_rejects_non_integer_document_id(self):
        response = self.client.get("/api/v1/knowledge/documents/..%2F1/original")
        self.assertIn(response.status_code, {404, 422})

    def test_authenticated_accessible_article_exact_version_succeeds(self):
        response = self.client.get("/api/v1/knowledge/articles/1?version_id=1&chunk_id=10")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source_document_id"], 1)
        self.assertEqual(body["document_version_id"], 1)
        self.assertEqual(body["current_document_version_id"], 2)
        self.assertFalse(body["is_current_version"])
        self.assertEqual(body["title"], "Article ancien")
        self.assertEqual(body["kb_code"], "KB-OLD")
        self.assertEqual(body["requested_chunk"]["chunk_id"], 10)
        rendered = str(body)
        self.assertNotIn("source_path", rendered)
        self.assertNotIn("storage_path", rendered)
        self.assertNotIn("checksum", rendered)
        self.assertNotIn("/internal/", rendered)

    def test_current_version_is_used_when_no_version_is_requested(self):
        response = self.client.get("/api/v1/knowledge/articles/1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["document_version_id"], 2)
        self.assertTrue(body["is_current_version"])
        self.assertEqual(body["title"], "Article courant")

    def test_unauthenticated_request_is_rejected(self):
        del self.app.dependency_overrides[get_current_user]
        response = self.client.get("/api/v1/knowledge/articles/1")
        self.assertEqual(response.status_code, 401)

    def test_inaccessible_article_is_hidden(self):
        with patch("app.services.knowledge_article_service.can_read_document", return_value=False):
            response = self.client.get("/api/v1/knowledge/articles/1")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Article not found."})

    def test_missing_document_version_or_chunk_returns_safe_404(self):
        for path in (
            "/api/v1/knowledge/articles/999",
            "/api/v1/knowledge/articles/1?version_id=999",
            "/api/v1/knowledge/articles/1?version_id=1&chunk_id=20",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Article not found."})


if __name__ == "__main__":
    unittest.main()
