from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import requests

from app.auth_dependencies import get_current_user
from app.config import CacheSettings
from app.routes import router
from app.services.retrieval_logging_service import ChatSessionAccessError
from app.services import cache_service, ollama_service


SOURCE = {
    "id": "chunk-1",
    "rank": 1,
    "score": 0.9,
    "chunk_id": 101,
    "source_document_id": 201,
    "document_version_id": 301,
    "kb_code": "KB",
    "article_title": "Article",
    "file_name": "article.docx",
    "section_title": "Section",
    "text": "Réponse documentée.",
}
AUDIT = {
    "audit_logged": True,
    "retrieval_id": 7,
    "user_id": 42,
    "session_id": 8,
    "message_id": 9,
    "user_message_id": 9,
    "assistant_message_id": 10,
    "logged_results": 1,
    "missing_chunk_ids": [],
}


class FakePreparedStream:
    def __init__(self, items):
        self.model = "llama3.2:3b"
        self.context_chunks_selected = 1
        self.context_chunks_included = 1
        self.context_chars = 100
        self.items = items

    def chunks(self):
        yield from self.items


class FakeResponse:
    def __init__(self, lines):
        self.lines = lines
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        yield from self.lines

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class StreamingChatTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.user = SimpleNamespace(user_id=42, role="agent", is_active=True)
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)

    def request(self, items):
        with (
            patch("app.routes.search_chunks", return_value=[SOURCE]),
            patch(
                "app.routes.compose_answer",
                return_value={"answer": "fallback", "confidence": "high"},
            ),
            patch("app.routes.log_retrieval_event", return_value=AUDIT) as audit,
            patch(
                "app.routes.stream_answer_with_ollama",
                return_value=FakePreparedStream(items),
            ),
            patch("app.routes.attach_source_database_metadata", side_effect=lambda chunks: chunks),
            patch("app.routes.get_bounded_conversation_history", return_value=[]),
            patch("app.routes.create_assistant_message", return_value=10),
            patch("app.routes.update_assistant_message") as update,
        ):
            response = self.client.post(
                "/api/v1/chat/stream", json={"question": "Question ?"}
            )
        events = [json.loads(line) for line in response.text.splitlines()]
        self.last_update_assistant_message = update
        return response, events, audit

    def test_normal_streaming_is_valid_ndjson(self):
        response, events, _audit = self.request(
            [
                {"type": "token", "text": "Bon"},
                {"type": "token", "text": "jour"},
                {"type": "ollama_done"},
            ]
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))
        self.assertEqual([event["type"] for event in events], ["metadata", "token", "token", "done"])
        self.assertEqual(events[-1], {"type": "done", "status": "complete",
                                      "partial": False, "message_id": 10,
                                      "assistant_message_id": 10})

    def test_empty_stream_terminates_cleanly(self):
        _response, events, _audit = self.request([])
        self.assertEqual(events[-2]["code"], "empty_stream")
        self.assertEqual(events[-1]["status"], "empty")

    def test_timeout_terminates_cleanly_without_exception_details(self):
        def timed_out():
            raise requests.Timeout("secret internal URL")
            yield

        _response, events, _audit = self.request(timed_out())
        rendered = json.dumps(events)
        self.assertEqual(events[-2]["code"], "timeout")
        self.assertNotIn("secret", rendered)
        self.assertNotIn("Traceback", rendered)

    def test_utf8_tokens_round_trip(self):
        _response, events, _audit = self.request(
            [{"type": "token", "text": "Réponse été 🚀"}, {"type": "ollama_done"}]
        )
        self.assertEqual(events[1]["text"], "Réponse été 🚀")

    def test_audit_occurs_exactly_once_with_authenticated_user(self):
        _response, events, audit = self.request(
            [{"type": "token", "text": "ok"}, {"type": "ollama_done"}]
        )
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["actor_user_id"], 42)
        self.assertEqual(events[0]["audit"]["user_id"], 42)

    def test_performance_metrics_keep_existing_fields(self):
        with patch("app.routes.log_performance") as logged:
            self.request([{"type": "token", "text": "ok"}, {"type": "ollama_done"}])
        values = logged.call_args.args[2]
        self.assertEqual(logged.call_args.args[0], "chat_stream_performance")
        for field in ("total_ms", "time_to_first_token_ms", "generation_ms", "ollama_ms", "audit_ms", "milvus_ms"):
            self.assertIn(field, values)

    def test_authentication_is_required(self):
        del self.app.dependency_overrides[get_current_user]
        response = self.client.post(
            "/api/v1/chat/stream", json={"question": "Question ?"}
        )
        self.assertEqual(response.status_code, 401)

    def test_unknown_role_is_forbidden(self):
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            user_id=42, role="manager", is_active=True
        )
        response = self.client.post(
            "/api/v1/chat/stream", json={"question": "Question ?"}
        )
        self.assertEqual(response.status_code, 403)


    def test_follow_up_reuses_owned_session_and_keeps_current_retrieval_query(self):
        with (
            patch("app.routes.ensure_chat_session_access") as ensure_access,
            patch("app.routes.search_chunks", return_value=[SOURCE]) as search,
            patch("app.routes.compose_answer", return_value={"answer": "fallback", "confidence": "high"}),
            patch("app.routes.generate_answer_with_ollama", return_value={"answer": "legacy", "model": "llama3.2:3b"}) as generate,
            patch("app.routes.log_retrieval_event", return_value={**AUDIT, "session_id": 8, "user_message_id": 11}),
            patch("app.routes.log_assistant_message", return_value=12),
            patch("app.routes.attach_source_database_metadata", side_effect=lambda chunks: chunks),
            patch("app.routes.get_bounded_conversation_history", return_value=[{"role": "user", "content": "Avant"}]) as history,
        ):
            response = self.client.post(
                "/api/v1/chat", json={"question": "Question de suivi ?", "session_id": 8}
            )
        self.assertEqual(response.status_code, 200)
        ensure_access.assert_called_once_with(session_id=8, user_id=42)
        self.assertEqual(search.call_args.kwargs["query"], "Question de suivi ?")
        self.assertEqual(generate.call_args.kwargs["conversation_history"], [{"role": "user", "content": "Avant"}])
        history.assert_called_once_with(session_id=8, user_id=42, before_message_id=11)
        self.assertEqual(response.json()["audit"]["session_id"], 8)
        self.assertEqual(response.json()["audit"]["assistant_message_id"], 12)

    def test_cross_user_session_reuse_is_rejected_before_retrieval(self):
        with (
            patch("app.routes.ensure_chat_session_access", side_effect=ChatSessionAccessError("Chat session is not available.")),
            patch("app.routes.search_chunks") as search,
        ):
            response = self.client.post(
                "/api/v1/chat/stream", json={"question": "Question ?", "session_id": 999}
            )
        self.assertEqual(response.status_code, 403)
        search.assert_not_called()

    def test_interrupted_stream_updates_persisted_assistant_with_partial_answer(self):
        def interrupted():
            yield {"type": "token", "text": "partiel"}
            raise requests.RequestException("network")

        _response, events, _audit = self.request(interrupted())
        self.assertEqual(events[-2]["code"], "stream_interrupted")
        self.assertEqual(events[-1]["partial"], True)
        self.last_update_assistant_message.assert_called_once()
        self.assertEqual(self.last_update_assistant_message.call_args.kwargs["message_id"], 10)
        self.assertEqual(self.last_update_assistant_message.call_args.kwargs["answer"], "partiel")

    def test_legacy_chat_endpoint_is_unchanged(self):
        with (
            patch("app.routes.search_chunks", return_value=[SOURCE]),
            patch("app.routes.compose_answer", return_value={"answer": "fallback", "confidence": "high"}),
            patch("app.routes.generate_answer_with_ollama", return_value={"answer": "legacy", "model": "llama3.2:3b"}),
            patch("app.routes.log_retrieval_event", return_value=AUDIT),
            patch("app.routes.attach_source_database_metadata", side_effect=lambda chunks: chunks),
            patch("app.routes.get_bounded_conversation_history", return_value=[]),
        ):
            response = self.client.post("/api/v1/chat", json={"question": "Question ?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "legacy")
        self.assertEqual(response.json()["generation_provider"], "ollama")


class _FakeAnswerCacheRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True


ANSWER_CACHE_SETTINGS = CacheSettings(
    redis_url="redis://unused:6379/0",
    enabled=True,
    namespace="tests-stream",
    default_ttl_seconds=30,
    search_ttl_seconds=30,
    embedding_ttl_seconds=60,
    answer_ttl_seconds=60,
    version="v1",
)


class OllamaStreamConsumerTests(unittest.TestCase):
    def setUp(self):
        cache_service._client = None
        self.addCleanup(setattr, cache_service, "_client", None)

    def settings(self):
        return SimpleNamespace(
            selected_model="llama3.2:3b",
            max_context_chars=12000,
            url="http://ollama.invalid/api/generate",
            keep_alive="10m",
            temperature=0.1,
            num_ctx=4096,
            num_predict=350,
            request_timeout_seconds=12.5,
        )

    def prepared(self, lines):
        response = FakeResponse(lines)
        session = FakeSession(response)
        with (
            patch("app.services.ollama_service.get_ollama_settings", return_value=self.settings()),
            patch("app.services.ollama_service.get_ollama_session", return_value=session),
        ):
            stream = ollama_service.stream_answer_with_ollama("Question ?", [SOURCE])
            events = list(stream.chunks())
        return events, response, session

    def test_malformed_chunks_are_skipped(self):
        events, response, _session = self.prepared(
            [b"not-json", b"\xff", b"[]", b'{"response":"ok"}', b'{"done":true}']
        )
        self.assertEqual(events[0], {"type": "token", "text": "ok"})
        self.assertEqual(events[-1]["type"], "ollama_done")
        self.assertTrue(response.closed)

    def test_stream_request_preserves_timeout_and_stream_flag(self):
        _events, _response, session = self.prepared([b'{"done":true}'])
        kwargs = session.calls[0][1]
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout"], 12.5)
        self.assertTrue(kwargs["json"]["stream"])

    def test_client_disconnect_closes_ollama_response(self):
        response = FakeResponse([b'{"response":"first"}', b'{"response":"second"}'])
        session = FakeSession(response)
        with (
            patch("app.services.ollama_service.get_ollama_settings", return_value=self.settings()),
            patch("app.services.ollama_service.get_ollama_session", return_value=session),
        ):
            stream = ollama_service.stream_answer_with_ollama("Question ?", [SOURCE])
            iterator = stream.chunks()
            self.assertEqual(next(iterator)["text"], "first")
            iterator.close()
        self.assertTrue(response.closed)

    def test_repeated_stream_reuses_cached_answer_without_a_second_ollama_call(self):
        cache_service._client = _FakeAnswerCacheRedis()

        with (
            patch("app.services.ollama_service.get_ollama_settings", return_value=self.settings()),
            patch("app.services.ollama_service.get_cache_settings", return_value=ANSWER_CACHE_SETTINGS),
        ):
            first_response = FakeResponse(
                [b'{"response":"Bonjour"}', b'{"response":" le monde"}', b'{"done":true}']
            )
            first_session = FakeSession(first_response)
            with patch(
                "app.services.ollama_service.get_ollama_session", return_value=first_session
            ):
                stream1 = ollama_service.stream_answer_with_ollama("Question identique ?", [SOURCE])
                events1 = list(stream1.chunks())
            self.assertEqual(len(first_session.calls), 1)
            full_answer = "".join(
                event["text"] for event in events1 if event["type"] == "token"
            )
            self.assertEqual(full_answer, "Bonjour le monde")

            second_session = FakeSession(FakeResponse([b'{"done":true}']))
            with patch(
                "app.services.ollama_service.get_ollama_session", return_value=second_session
            ):
                stream2 = ollama_service.stream_answer_with_ollama("Question identique ?", [SOURCE])
                events2 = list(stream2.chunks())

        self.assertEqual(second_session.calls, [])
        self.assertEqual(events2[0], {"type": "token", "text": full_answer})
        self.assertEqual(events2[-1]["type"], "ollama_done")

    def test_different_question_does_not_reuse_cached_answer(self):
        cache_service._client = _FakeAnswerCacheRedis()

        with (
            patch("app.services.ollama_service.get_ollama_settings", return_value=self.settings()),
            patch("app.services.ollama_service.get_cache_settings", return_value=ANSWER_CACHE_SETTINGS),
        ):
            first_session = FakeSession(
                FakeResponse([b'{"response":"Reponse A"}', b'{"done":true}'])
            )
            with patch(
                "app.services.ollama_service.get_ollama_session", return_value=first_session
            ):
                stream1 = ollama_service.stream_answer_with_ollama("Premiere question ?", [SOURCE])
                list(stream1.chunks())

            second_session = FakeSession(
                FakeResponse([b'{"response":"Reponse B"}', b'{"done":true}'])
            )
            with patch(
                "app.services.ollama_service.get_ollama_session", return_value=second_session
            ):
                stream2 = ollama_service.stream_answer_with_ollama("Deuxieme question ?", [SOURCE])
                events2 = list(stream2.chunks())

        self.assertEqual(len(second_session.calls), 1)
        self.assertEqual(
            [event["text"] for event in events2 if event["type"] == "token"],
            ["Reponse B"],
        )

    def test_closure_code_questions_request_direct_rule_only_prompting(self):
        prompt = ollama_service.build_grounded_prompt(
            question="Bonjour, le technicien a refait le branchement au PB quel code de cloture dois je utiliser pour cloturer ?",
            retrieved_chunks=[{
                **SOURCE,
                "chunk_type": "rule",
                "text": (
                    "Si la typologie fibre sélectionnée est « Refait Branchement PB », "
                    "alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20."
                ),
            }],
            context=(
                "Source ID: SAV-CLOT-016::0047\n"
                "Article: Aide clôture SAV fibre\n"
                "Section: Règles métier explicites\n"
                "Contenu: Si la typologie fibre sélectionnée est « Refait Branchement PB », "
                "alors le code de clôture Retail est « FTO DEF PB DIVERS » et le code unique est 20."
            ),
            conversation_history=[{"role": "assistant", "content": "Ancien sujet"}],
        )
        self.assertIn("Réponds uniquement avec cette règle prioritaire.", prompt)
        self.assertIn("N'ajoute pas de cas alternatifs", prompt)
        self.assertIn("code unique", prompt)
        self.assertIn("HISTORIQUE RÉCENT", prompt)

    def test_closure_code_prompt_does_not_prioritize_generic_question_chunk(self):
        prompt = ollama_service.build_grounded_prompt(
            question="Quel code utiliser pour clôture en réussite ?",
            retrieved_chunks=[
                {
                    **SOURCE,
                    "id": "FDE-ECHECS-015::0013",
                    "chunk_type": "question",
                    "text": "Quel code de clôture utiliser ?",
                },
                {
                    **SOURCE,
                    "id": "FTTH-FIABILISATION-CLOTURE-007::0046",
                    "chunk_type": "rule",
                    "text": "Si le commentaire d’expertise sélectionné est « Réparation définitive », alors le code de clôture à utiliser est « FTO DEF ---- ».",
                },
            ],
            context=(
                "Source ID: FDE-ECHECS-015::0013\n"
                "Article: Échecs FDE\n"
                "Section: Questions\n"
                "Contenu: Quel code de clôture utiliser ?\n\n---\n\n"
                "Source ID: FTTH-FIABILISATION-CLOTURE-007::0046\n"
                "Article: Fiabilisation clôture\n"
                "Section: Règles métier explicites\n"
                "Contenu: Si le commentaire d’expertise sélectionné est « Réparation définitive », alors le code de clôture à utiliser est « FTO DEF ---- »."
            ),
        )

        self.assertNotIn("Réponds uniquement avec cette règle prioritaire.", prompt)
        self.assertIn("ne choisis pas un code provenant d'une règle de rang inférieur", prompt)


if __name__ == "__main__":
    unittest.main()
