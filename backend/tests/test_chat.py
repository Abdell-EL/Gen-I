from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import requests

from app.auth_dependencies import get_current_user
from app.routes import router
from app.services import ollama_service


SOURCE = {
    "id": "chunk-1",
    "rank": 1,
    "score": 0.9,
    "article_title": "Article",
    "section_title": "Section",
    "text": "Réponse documentée.",
}
AUDIT = {
    "audit_logged": True,
    "retrieval_id": 7,
    "user_id": 42,
    "session_id": 8,
    "message_id": 9,
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
        ):
            response = self.client.post(
                "/api/v1/chat/stream", json={"question": "Question ?"}
            )
        events = [json.loads(line) for line in response.text.splitlines()]
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
        self.assertEqual(events[-1], {"type": "done", "status": "complete", "partial": False})

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

    def test_legacy_chat_endpoint_is_unchanged(self):
        with (
            patch("app.routes.search_chunks", return_value=[SOURCE]),
            patch("app.routes.compose_answer", return_value={"answer": "fallback", "confidence": "high"}),
            patch("app.routes.generate_answer_with_ollama", return_value={"answer": "legacy", "model": "llama3.2:3b"}),
            patch("app.routes.log_retrieval_event", return_value=AUDIT),
        ):
            response = self.client.post("/api/v1/chat", json={"question": "Question ?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "legacy")
        self.assertEqual(response.json()["generation_provider"], "ollama")


class OllamaStreamConsumerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
