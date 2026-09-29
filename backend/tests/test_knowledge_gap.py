from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import router as admin_router
from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.models import KnowledgeGap, User
from app.services.knowledge_gap_service import (
    KnowledgeGapNotFoundError,
    answer_indicates_missing_information,
    is_low_confidence,
    list_knowledge_gaps,
    record_knowledge_gap_if_needed,
    resolve_knowledge_gap,
)


class DetectionHeuristicTests(unittest.TestCase):
    def test_recognizes_known_missing_information_phrasing(self):
        answer = "Cette information n'est pas présente dans les sources disponibles."
        self.assertTrue(answer_indicates_missing_information(answer))

    def test_normal_answer_does_not_trigger_missing_information(self):
        answer = "Le code a utiliser est le 4521 pour une demande d'autorisation voisinage."
        self.assertFalse(answer_indicates_missing_information(answer))

    def test_empty_answer_does_not_trigger_missing_information(self):
        self.assertFalse(answer_indicates_missing_information(""))
        self.assertFalse(answer_indicates_missing_information(None))

    def test_low_and_unknown_confidence_are_low_confidence(self):
        self.assertTrue(is_low_confidence("low"))
        self.assertTrue(is_low_confidence("unknown"))
        self.assertTrue(is_low_confidence(None))

    def test_high_and_medium_confidence_are_not_low_confidence(self):
        self.assertFalse(is_low_confidence("high"))
        self.assertFalse(is_low_confidence("medium"))


class KnowledgeGapServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(
            full_name="Agent One", email="agent@example.com", role="agent",
            is_active=True, password_hash="hash", activation_status="active",
        )
        self.admin = User(
            full_name="Admin", email="admin@example.com", role="admin",
            is_active=True, password_hash="hash", activation_status="active",
        )
        self.db.add_all([self.user, self.admin])
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.admin)

        self.session_local_patcher = patch(
            "app.services.knowledge_gap_service.SessionLocal", self.Session,
        )
        self.session_local_patcher.start()

    def tearDown(self):
        self.session_local_patcher.stop()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_records_a_gap_when_answer_text_indicates_missing_information(self):
        gap_id = record_knowledge_gap_if_needed(
            user_id=self.user.user_id,
            question_text="Quelle est la procedure X ?",
            answer_text="Cette information n'est pas présente dans les sources disponibles.",
            confidence="high",
        )
        self.assertIsNotNone(gap_id)
        gap = self.db.get(KnowledgeGap, gap_id)
        self.assertTrue(gap.text_indicates_missing)
        self.assertFalse(gap.low_confidence)
        self.assertEqual(gap.status, "open")

    def test_records_a_gap_when_confidence_is_low(self):
        gap_id = record_knowledge_gap_if_needed(
            user_id=self.user.user_id,
            question_text="Quelle est la procedure Y ?",
            answer_text="Voici la reponse complete et correcte.",
            confidence="low",
        )
        self.assertIsNotNone(gap_id)
        gap = self.db.get(KnowledgeGap, gap_id)
        self.assertFalse(gap.text_indicates_missing)
        self.assertTrue(gap.low_confidence)

    def test_does_not_record_a_gap_for_a_confident_complete_answer(self):
        gap_id = record_knowledge_gap_if_needed(
            user_id=self.user.user_id,
            question_text="Quelle est la procedure Z ?",
            answer_text="Voici la reponse complete et correcte.",
            confidence="high",
        )
        self.assertIsNone(gap_id)
        self.assertEqual(self.db.query(KnowledgeGap).count(), 0)

    def test_list_knowledge_gaps_filters_by_status_and_paginates(self):
        for index in range(3):
            record_knowledge_gap_if_needed(
                user_id=self.user.user_id,
                question_text=f"Question {index}",
                answer_text="n'est pas présente dans les sources disponibles",
                confidence="high",
            )
        result = list_knowledge_gaps(self.db, page=1, page_size=2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["items"]), 2)

        open_result = list_knowledge_gaps(self.db, status="open")
        self.assertEqual(open_result["total"], 3)
        resolved_result = list_knowledge_gaps(self.db, status="resolved")
        self.assertEqual(resolved_result["total"], 0)

    def test_resolve_knowledge_gap_updates_status_and_notes(self):
        gap_id = record_knowledge_gap_if_needed(
            user_id=self.user.user_id,
            question_text="Question sans reponse",
            answer_text="n'est pas présente dans les sources disponibles",
            confidence="high",
        )
        updated = resolve_knowledge_gap(
            self.db,
            gap_id=gap_id,
            resolved_by=self.admin.user_id,
            resolution_notes="Ajoute au document X",
        )
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["resolved_by"], self.admin.user_id)
        self.assertIsNotNone(updated["resolved_at"])

    def test_resolve_missing_knowledge_gap_raises(self):
        with self.assertRaises(KnowledgeGapNotFoundError):
            resolve_knowledge_gap(
                self.db,
                gap_id=999999,
                resolved_by=self.admin.user_id,
                resolution_notes=None,
            )


class KnowledgeGapAdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.admin = User(
            full_name="Admin", email="admin@example.com", role="admin",
            is_active=True, password_hash="hash", activation_status="active",
        )
        self.db.add(self.admin)
        self.db.commit()
        self.db.refresh(self.admin)

        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

        self.session_local_patcher = patch(
            "app.services.knowledge_gap_service.SessionLocal", self.Session,
        )
        self.session_local_patcher.start()

    def tearDown(self):
        self.session_local_patcher.stop()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_list_and_resolve_via_admin_api(self):
        gap_id = record_knowledge_gap_if_needed(
            user_id=self.admin.user_id,
            question_text="Question sans reponse",
            answer_text="n'est pas présente dans les sources disponibles",
            confidence="high",
        )

        list_response = self.client.get("/api/v1/admin/knowledge-gaps")
        self.assertEqual(list_response.status_code, 200)
        body = list_response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["gap_id"], gap_id)

        resolve_response = self.client.post(
            f"/api/v1/admin/knowledge-gaps/{gap_id}/resolve",
            json={"status": "resolved", "resolution_notes": "Documente"},
        )
        self.assertEqual(resolve_response.status_code, 200)
        self.assertEqual(resolve_response.json()["status"], "resolved")

        filtered = self.client.get("/api/v1/admin/knowledge-gaps", params={"status": "open"})
        self.assertEqual(filtered.json()["total"], 0)

    def test_resolve_unknown_gap_returns_404(self):
        response = self.client.post(
            "/api/v1/admin/knowledge-gaps/999999/resolve",
            json={"status": "resolved"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
