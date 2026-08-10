from __future__ import annotations

import inspect
import json
import logging
import os
from types import SimpleNamespace
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import requests

from app.admin_routes import router as admin_router
from app.auth_dependencies import get_current_user
from app.auth_routes import router as auth_router
from app.config import AuthSettings, CacheSettings, get_ollama_settings
from app.routes import router as api_router
from app.services import (
    admin_ingestion_service,
    cache_service,
    ollama_service,
    retrieval_service,
)
from app.services.cache_service import (
    CacheRead,
    bounded_wait_for_json,
    embedding_cache_key,
    query_hash,
    retrieval_cache_key,
)
from app.services.performance_service import log_performance


CACHE_SETTINGS = CacheSettings(
    redis_url="redis://unused:6379/0",
    enabled=True,
    namespace="tests",
    default_ttl_seconds=30,
    search_ttl_seconds=30,
    embedding_ttl_seconds=60,
    version="v1",
)


class FakeRedis:
    def __init__(self, unavailable=False):
        self.values = {}
        self.unavailable = unavailable
        self.closed = False

    def _check(self):
        if self.unavailable:
            raise ConnectionError("redis unavailable")

    def get(self, key):
        self._check()
        return self.values.get(key)

    def set(self, key, value, ex=None, nx=False):
        self._check()
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self._check()
        return int(self.values.pop(key, None) is not None)

    def incr(self, key):
        self._check()
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    def eval(self, _script, _count, key, token):
        self._check()
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0

    def ping(self):
        self._check()
        return True

    def close(self):
        self.closed = True


class FakeModel:
    def __init__(self):
        self.encode_calls = 0

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, _text, normalize_embeddings=True):
        self.encode_calls += 1
        return [0.1, 0.2, 0.3]


class FakeEntity:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


class FakeHit:
    def __init__(self):
        self.distance = 0.91
        self.entity = FakeEntity(
            {
                "id": "chunk-1",
                "text": "Evidence",
                "kb_code": "KB-1",
                "article_title": "Article",
                "section_title": "Section",
                "chunk_type": "procedure",
                "priority": "high",
                "metadata": {},
            }
        )


class FakeCollection:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def search(self, **_kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("milvus unavailable")
        return [[FakeHit()]]


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"response": "Réponse", "prompt_eval_count": 10, "eval_count": 5}


class Phase4BCacheTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        cache_service._client = self.redis
        self.settings_patch = patch(
            "app.services.retrieval_service.get_cache_settings",
            return_value=CACHE_SETTINGS,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.model = FakeModel()
        self.collection = FakeCollection()
        self.model_patch = patch(
            "app.services.retrieval_service.get_embedding_model",
            return_value=self.model,
        )
        self.collection_patch = patch(
            "app.services.retrieval_service.get_collection",
            return_value=self.collection,
        )
        self.lexical_patch = patch(
            "app.services.retrieval_service._lexical_current_version_candidates",
            return_value=[],
        )
        self.model_patch.start()
        self.collection_patch.start()
        self.lexical_patch.start()
        self.addCleanup(self.model_patch.stop)
        self.addCleanup(self.collection_patch.stop)
        self.addCleanup(self.lexical_patch.stop)

    def tearDown(self):
        cache_service._client = None

    def test_cache_disabled_uses_normal_path(self):
        disabled = CacheSettings(**{**CACHE_SETTINGS.__dict__, "enabled": False})
        with patch(
            "app.services.retrieval_service.get_cache_settings", return_value=disabled
        ):
            result = retrieval_service.search_chunks("disabled cache", 1)
        self.assertEqual(result[0]["id"], "chunk-1")
        self.assertEqual(self.collection.calls, 1)

    def test_redis_unavailable_falls_back_to_normal_path(self):
        cache_service._client = FakeRedis(unavailable=True)
        result = retrieval_service.search_chunks("redis down", 1)
        self.assertEqual(result[0]["id"], "chunk-1")
        self.assertEqual(self.collection.calls, 1)

    def test_embedding_cache_miss_computes_and_stores(self):
        vector = retrieval_service.embed_query("repeat query")
        self.assertEqual(vector, [0.1, 0.2, 0.3])
        self.assertEqual(self.model.encode_calls, 1)
        key = embedding_cache_key(CACHE_SETTINGS, retrieval_service.EMBEDDING_MODEL, "repeat query")
        self.assertIn(key, self.redis.values)

    def test_embedding_cache_hit_avoids_computation(self):
        key = embedding_cache_key(CACHE_SETTINGS, retrieval_service.EMBEDDING_MODEL, "repeat query")
        self.redis.values[key] = json.dumps(
            {"dimension": 3, "vector": [0.4, 0.5, 0.6]}
        )
        with patch("app.services.retrieval_service._encode_query") as encode:
            vector = retrieval_service.embed_query("  REPEAT   QUERY ")
        self.assertEqual(vector, [0.4, 0.5, 0.6])
        encode.assert_not_called()

    def test_retrieval_cache_hit_avoids_milvus(self):
        first = retrieval_service.search_chunks("cached retrieval", 1)
        second = retrieval_service.search_chunks("cached retrieval", 1)
        self.assertEqual(first, second)
        self.assertEqual(self.collection.calls, 1)

    def test_corrupt_entries_are_ignored_and_replaced(self):
        key = embedding_cache_key(CACHE_SETTINGS, retrieval_service.EMBEDDING_MODEL, "bad vector")
        self.redis.values[key] = json.dumps({"dimension": 3, "vector": ["bad"]})
        vector = retrieval_service.embed_query("bad vector")
        self.assertEqual(vector, [0.1, 0.2, 0.3])
        self.assertEqual(self.model.encode_calls, 1)

    def test_failed_retrieval_is_not_cached(self):
        failing = FakeCollection(fail=True)
        with patch("app.services.retrieval_service.get_collection", return_value=failing):
            with self.assertRaises(RuntimeError):
                retrieval_service.search_chunks("failed retrieval", 1)
        retrieval_keys = [key for key in self.redis.values if ":retrieval:" in key]
        self.assertEqual(retrieval_keys, [])

    def test_hybrid_lexical_candidate_recovers_refait_branchement_pb(self):
        with patch(
            "app.services.retrieval_service._lexical_current_version_candidates",
            return_value=[
                {
                    "rank": 0,
                    "score": 0.99,
                    "id": "SAV-CLOT-016::0047",
                    "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
                    "kb_code": "SAV-CLOT-016",
                    "article_title": "SAV-CLOT-016 – Aide à la clôture SAV fibre : typologie, codes de clôture Retail et Wholesale",
                    "section_title": "Règles métier explicites",
                    "chunk_type": "rule",
                    "priority": "critical",
                    "metadata": {"document_id": 28, "version_id": 28},
                }
            ],
        ):
            result = retrieval_service.search_chunks("Refait Branchement PB", 5)
        self.assertTrue(any(item["id"] == "SAV-CLOT-016::0047" for item in result))

    def test_hybrid_lexical_candidate_recovers_exact_code(self):
        with patch(
            "app.services.retrieval_service._lexical_current_version_candidates",
            return_value=[
                {
                    "rank": 0,
                    "score": 0.99,
                    "id": "SAV-CLOT-016::0047",
                    "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
                    "kb_code": "SAV-CLOT-016",
                    "article_title": "SAV-CLOT-016 – Aide à la clôture SAV fibre : typologie, codes de clôture Retail et Wholesale",
                    "section_title": "Règles métier explicites",
                    "chunk_type": "rule",
                    "priority": "critical",
                    "metadata": {"document_id": 28, "version_id": 28},
                }
            ],
        ):
            result = retrieval_service.search_chunks("FTO DEF PB DIVERS", 5)
        self.assertTrue(any(item["id"] == "SAV-CLOT-016::0047" for item in result))

    def test_hybrid_lexical_candidate_recovers_natural_paraphrase(self):
        with patch(
            "app.services.retrieval_service._lexical_current_version_candidates",
            return_value=[
                {
                    "rank": 0,
                    "score": 0.99,
                    "id": "SAV-CLOT-016::0047",
                    "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
                    "kb_code": "SAV-CLOT-016",
                    "article_title": "SAV-CLOT-016 – Aide à la clôture SAV fibre : typologie, codes de clôture Retail et Wholesale",
                    "section_title": "Règles métier explicites",
                    "chunk_type": "rule",
                    "priority": "critical",
                    "metadata": {"document_id": 28, "version_id": 28},
                }
            ],
        ):
            result = retrieval_service.search_chunks(
                "Bonjour, le technicien a refait le branchement au PB quel code de cloture dois je utiliser pour cloturer ?",
                5,
            )
        self.assertTrue(any(item["id"] == "SAV-CLOT-016::0047" for item in result))

    def test_lexical_candidate_has_all_embedding_text_fields(self):
        candidate = {
            "rank": 0,
            "score": 0.99,
            "id": "SAV-CLOT-016::0047",
            "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
            "kb_code": "SAV-CLOT-016",
            "article_title": "SAV-CLOT-016 – Aide à la clôture SAV fibre : typologie, codes de clôture Retail et Wholesale",
            "file_name": "SAV-CLOT-016_Aide_cloture_SAV_fibre_codes_Retail_Wholesale.docx",
            "section_title": "Règles métier explicites",
            "section_type": "rules",
            "chunk_type": "rule",
            "priority": "critical",
            "word_count": 42,
            "metadata": {"document_id": 28, "version_id": 28},
        }
        built = retrieval_service.build_embedding_text(candidate)
        self.assertIn("Fichier source: SAV-CLOT-016_Aide_cloture_SAV_fibre_codes_Retail_Wholesale.docx", built)
        self.assertIn("Section: Règles métier explicites", built)
        self.assertIn("Type de section: rules", built)
        self.assertIn("Type de fragment: rule", built)

    def test_acronym_discrimination_prefers_pb_over_pm_for_refait_branchement(self):
        pb_score = retrieval_service._lexical_rerank_score(
            "Refait Branchement PB",
            {
                "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
                "kb_code": "SAV-CLOT-016",
                "article_title": "Aide à la clôture SAV fibre",
                "section_title": "Règles métier explicites",
                "chunk_type": "rule",
                "priority": "critical",
            },
        )
        pm_score = retrieval_service._lexical_rerank_score(
            "Refait Branchement PB",
            {
                "text": "Si la typologie fibre sélectionnée est « Refait branchement PM », alors le code de clôture Retail est « FTO DEF PM PM » et le code unique est 21.",
                "kb_code": "SAV-CLOT-016",
                "article_title": "Aide à la clôture SAV fibre",
                "section_title": "Règles métier explicites",
                "chunk_type": "rule",
                "priority": "critical",
            },
        )
        self.assertGreater(pb_score, pm_score)

    def test_acronym_discrimination_prefers_pb_over_pm_for_closure_code_routing(self):
        pb_score = retrieval_service._lexical_rerank_score(
            "Refait Branchement PB",
            {
                "text": "Si la typologie fibre sélectionnée est « Refait Branchement PB », alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20.",
                "kb_code": "SAV-CLOT-016",
                "article_title": "Aide à la clôture SAV fibre",
                "section_title": "Règles métier explicites",
                "chunk_type": "rule",
                "priority": "critical",
            },
        )
        pm_score = retrieval_service._lexical_rerank_score(
            "Refait Branchement PB",
            {
                "text": "Si la typologie fibre sélectionnée est « Refait branchement PM », alors le code de clôture Retail est « FTO DEF PM PM » et le code unique est 21.",
                "kb_code": "SAV-CLOT-016",
                "article_title": "Aide à la clôture SAV fibre",
                "section_title": "Règles métier explicites",
                "chunk_type": "rule",
                "priority": "critical",
            },
        )
        self.assertGreater(pb_score, pm_score)

    def test_existing_pm_regression_still_retrieves_f04_p03(self):
        with patch(
            "app.services.retrieval_service._lexical_current_version_candidates",
            return_value=[
                {
                    "rank": 0,
                    "score": 0.99,
                    "id": "F04-P03-003::0012",
                    "text": "problème de serrure PM",
                    "kb_code": "F04-P03-003",
                    "article_title": "F04-P03-003 – Codes de clôture et messages client F04 P03",
                    "section_title": "Règles métier explicites",
                    "chunk_type": "rule",
                    "priority": "critical",
                    "metadata": {"document_id": 99, "version_id": 99},
                }
            ],
        ):
            result = retrieval_service.search_chunks("problème de serrure PM", 5)
        self.assertTrue(any(item["id"] == "F04-P03-003::0012" for item in result))

    def test_cache_key_inputs_and_raw_query_privacy(self):
        base = dict(
            settings=CACHE_SETTINGS,
            retrieval_mode="semantic",
            query="Private Customer Question 123",
            top_k=5,
            filters={"kb": "A"},
            collection_name="collection-a",
            embedding_model="model-a",
            retrieval_config={"metric": "COSINE"},
            knowledge_generation=1,
        )
        original = retrieval_cache_key(**base)
        variants = []
        for field, value in (
            ("top_k", 6),
            ("filters", {"kb": "B"}),
            ("embedding_model", "model-b"),
            ("collection_name", "collection-b"),
            ("knowledge_generation", 2),
        ):
            changed = dict(base)
            changed[field] = value
            variants.append(retrieval_cache_key(**changed))
        self.assertEqual(len(set([original, *variants])), 6)
        self.assertNotIn("Private", original)
        self.assertNotIn("Question", original)
        self.assertIn(query_hash(base["query"]), json.dumps({"hash": query_hash(base["query"])}))

    def test_stampede_wait_is_bounded_and_fails_safely(self):
        started = time.perf_counter()
        result = bounded_wait_for_json("missing", wait_seconds=10, settings=CACHE_SETTINGS)
        elapsed = time.perf_counter() - started
        self.assertIsNone(result.value)
        self.assertLess(elapsed, 0.75)

    def test_cache_hit_still_audits_each_authenticated_user(self):
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        client = TestClient(app)
        audits = []

        def audit(**kwargs):
            audits.append(kwargs["actor_user_id"])
            return {"audit_logged": True, "user_id": kwargs["actor_user_id"]}

        def actual_search(**kwargs):
            return retrieval_service.search_chunks(**kwargs)

        with (
            patch("app.routes.search_chunks", side_effect=actual_search),
            patch("app.routes.log_retrieval_event", side_effect=audit),
        ):
            for user_id in (11, 22):
                app.dependency_overrides[get_current_user] = lambda value=user_id: SimpleNamespace(
                    user_id=value, role="agent", is_active=True
                )
                response = client.post("/api/v1/search", json={"query": "shared", "limit": 1})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["audit"]["user_id"], user_id)
        self.assertEqual(audits, [11, 22])
        self.assertEqual(self.collection.calls, 1)

    def test_audit_failure_discards_new_retrieval_cache(self):
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            user_id=11, role="agent", is_active=True
        )
        client = TestClient(app)

        def actual_search(**kwargs):
            return retrieval_service.search_chunks(**kwargs)

        with (
            patch("app.routes.search_chunks", side_effect=actual_search),
            patch("app.routes.log_retrieval_event", side_effect=RuntimeError("audit failed")),
        ):
            response = client.post(
                "/api/v1/search", json={"query": "do not retain", "limit": 1}
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            [key for key in self.redis.values if ":retrieval:" in key], []
        )


class Phase4BOllamaTests(unittest.TestCase):
    def tearDown(self):
        ollama_service.get_ollama_session.cache_clear()

    def test_keep_alive_and_bounded_options_are_passed(self):
        session = MagicMock()
        session.post.return_value = FakeResponse()
        env = {
            "OLLAMA_KEEP_ALIVE": "10m",
            "OLLAMA_NUM_CTX": "999999",
            "OLLAMA_NUM_PREDICT": "999999",
            "OLLAMA_TEMPERATURE": "99",
            "OLLAMA_REQUEST_TIMEOUT_SECONDS": "9999",
        }
        with patch.dict(os.environ, env), patch(
            "app.services.ollama_service.get_ollama_session", return_value=session
        ):
            result = ollama_service.generate_answer_with_ollama("Question", [])
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["keep_alive"], "10m")
        self.assertEqual(payload["options"]["num_ctx"], 32768)
        self.assertEqual(payload["options"]["num_predict"], 2048)
        self.assertEqual(payload["options"]["temperature"], 2.0)
        self.assertEqual(session.post.call_args.kwargs["timeout"], 600.0)
        self.assertEqual(result["model"], "llama3.2:3b")

    def test_fast_model_requires_explicit_enablement(self):
        with patch.dict(os.environ, {"OLLAMA_FAST_MODEL": "llama3.2:1b"}, clear=False):
            os.environ.pop("OLLAMA_USE_FAST_MODEL", None)
            self.assertEqual(get_ollama_settings().selected_model, "llama3.2:3b")
        with patch.dict(
            os.environ,
            {"OLLAMA_FAST_MODEL": "llama3.2:1b", "OLLAMA_USE_FAST_MODEL": "true"},
        ):
            self.assertEqual(get_ollama_settings().selected_model, "llama3.2:1b")

    def test_persistent_http_session_is_reused(self):
        with patch("app.services.ollama_service.requests.Session") as constructor:
            first = ollama_service.get_ollama_session()
            second = ollama_service.get_ollama_session()
        self.assertIs(first, second)
        constructor.assert_called_once_with()

    def test_context_budget_deduplicates_and_preserves_order_and_citations(self):
        chunks = [
            {"rank": 1, "id": "one", "article_title": "A", "text": "A" * 500},
            {"rank": 1, "id": "one", "article_title": "A", "text": "duplicate"},
            {"rank": 2, "id": "two", "article_title": "B", "text": "B" * 500},
        ]
        context = ollama_service.build_context(chunks, max_chars=800)
        self.assertEqual(context.count("Source ID: one"), 1)
        self.assertIn("Source ID: two", context)
        self.assertLess(context.index("Source ID: one"), context.index("Source ID: two"))
        self.assertLessEqual(len(context), 800)

    def test_ollama_timeout_keeps_current_chat_fallback_behavior(self):
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            user_id=7, role="agent", is_active=True
        )
        client = TestClient(app)
        with (
            patch("app.routes.search_chunks", return_value=[]),
            patch("app.routes.generate_answer_with_ollama", side_effect=requests.Timeout("timeout")),
            patch("app.routes.log_retrieval_event", return_value={
                "audit_logged": True, "user_id": 7, "session_id": 8,
                "message_id": 9, "user_message_id": 9,
            }),
            patch("app.routes.log_assistant_message", return_value=10),
            patch("app.routes.attach_source_database_metadata", side_effect=lambda chunks: chunks),
            patch("app.routes.get_bounded_conversation_history", return_value=[]),
        ):
            response = client.post("/api/v1/chat", json={"question": "test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["generation_provider"], "rule_based_fallback")
        self.assertIn("timeout", response.json()["generation_error"])


class Phase4BInstrumentationAndRouteTests(unittest.TestCase):
    def test_structured_log_has_durations_without_sensitive_values(self):
        with self.assertLogs("app.performance", level=logging.INFO) as captured:
            log_performance(
                "chat_performance",
                "request-1",
                {
                    "cache_hit": True,
                    "cache_status": "hit",
                    "embedding_ms": 1.2,
                    "milvus_ms": 2.3,
                    "postgres_ms": 0,
                    "ollama_ms": 3.4,
                    "audit_ms": 4.5,
                    "cache_lookup_ms": 0.5,
                    "total_ms": 12.0,
                    "token": "secret-token",
                    "password": "secret-password",
                    "prompt": "full prompt",
                },
            )
        message = captured.output[0]
        self.assertIn('"ollama_ms":3.4', message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("secret-password", message)
        self.assertNotIn("full prompt", message)

    def test_instrumentation_logger_failure_does_not_raise(self):
        with patch("app.services.performance_service.logger.info", side_effect=RuntimeError):
            log_performance("search_performance", "request-2", {"total_ms": 1})

    def test_admin_cache_status_access_and_safe_response(self):
        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1")
        client = TestClient(app)
        admin = SimpleNamespace(user_id=1, role="admin", is_active=True)
        agent = SimpleNamespace(user_id=2, role="agent", is_active=True)
        with patch(
            "app.admin_routes.get_cache_status",
            return_value={
                "enabled": True,
                "connected": False,
                "namespace": "tests",
                "version": "v1",
                "knowledge_generation": None,
            },
        ):
            app.dependency_overrides[get_current_user] = lambda: admin
            response = client.get("/api/v1/admin/cache/status")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("url", response.json())
            app.dependency_overrides[get_current_user] = lambda: agent
            self.assertEqual(client.get("/api/v1/admin/cache/status").status_code, 403)
            del app.dependency_overrides[get_current_user]
            self.assertEqual(client.get("/api/v1/admin/cache/status").status_code, 401)

    def test_auth_and_admin_responses_do_not_touch_cache(self):
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(admin_router, prefix="/api/v1")
        user = SimpleNamespace(
            user_id=1, full_name="Admin", email="admin.com",
            role="admin", is_active=True, password_hash="unused",
            department_id=None, created_at=None, updated_at=None,
        )
        app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(app)
        with (
            patch("app.services.cache_service.read_json") as cache_read,
            patch(
                "app.admin_routes.list_users",
                return_value={
                    "items": [], "page": 1, "page_size": 25,
                    "total": 0, "pages": 0,
                },
            ),
        ):
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
            self.assertEqual(client.get("/api/v1/admin/users").status_code, 200)
        cache_read.assert_not_called()

    def test_timings_use_monotonic_perf_counter(self):
        route_source = inspect.getsource(__import__("app.routes", fromlist=["chat"]))
        retrieval_source = inspect.getsource(retrieval_service)
        self.assertIn("time.perf_counter()", route_source)
        self.assertIn("time.perf_counter()", retrieval_source)
        self.assertNotIn("created_at", route_source[route_source.index("def semantic_search"):])

    def test_ingestion_generation_advance_is_after_commit_and_fail_open(self):
        source = inspect.getsource(admin_ingestion_service.ingest_docx_bytes)
        advance_at = source.index("advance_knowledge_generation()")
        self.assertLess(source.rfind("db.commit()", 0, advance_at), advance_at)
        self.assertIn("try:\n            advance_knowledge_generation()", source)


if __name__ == "__main__":
    unittest.main()
