from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts import benchmark_performance as benchmark


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise benchmark.requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, statuses=None, *, cache_connected=True):
        self.headers = {}
        self.statuses = list(statuses or [200, 200])
        self.cache_connected = cache_connected
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        if url.endswith("/api/v1/auth/signin"):
            return FakeResponse(
                200,
                {
                    "access_token": "super-secret-token",
                    "user": {"id": 17, "role": "agent"},
                },
            )
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        audit_id = 100 + self.calls
        audit = {"retrieval_id": audit_id, "user_id": 17}
        if url.endswith("/chat"):
            payload = {
                "question": json["question"],
                "answer": "Le code AV est utilisé.",
                "sources": [{"score": 0.8, "text": "Code AV"}],
                "audit": {**audit, "session_id": 200 + audit_id, "message_id": 300 + audit_id},
            }
        else:
            payload = {
                "query": json["query"],
                "results": [{"score": 0.8, "text": "Code AV"}],
                "audit": audit,
            }
        return FakeResponse(status, payload)

    def get(self, url, timeout=None):
        return FakeResponse(
            200,
            {
                "enabled": True,
                "connected": self.cache_connected,
                "namespace": "safe",
                "version": "v1",
                "knowledge_generation": 1,
            },
        )

    def close(self):
        pass


def fixture_file(directory: str) -> Path:
    path = Path(directory) / "fixtures.json"
    path.write_text(
        json.dumps(
            [{
                "name": "fixture",
                "query": "Quel code utiliser ?",
                "expected_terms": ["AV"],
                "routes": ["search", "chat"],
            }]
        ),
        encoding="utf-8",
    )
    return path


def args_for(fixtures: Path, **overrides) -> argparse.Namespace:
    values = {
        "base_url": "http://api.example.invalid",
        "email": "agent@example.invalid",
        "fixtures": fixtures,
        "repetitions": 1,
        "warmups": 0,
        "route": "search",
        "limit": 5,
        "timeout": 10.0,
        "json_output": None,
        "check_cache_status": False,
        "performance_log": None,
        "expect_cache_unavailable": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class BenchmarkCliSafetyTests(unittest.TestCase):
    def test_password_is_not_a_cli_argument(self):
        parser = benchmark.build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--email", "a@example.invalid", "--password", "secret"])
        self.assertNotIn("password", {action.dest for action in parser._actions})

    def test_token_is_never_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                report, code = benchmark.run_benchmark(
                    args_for(fixture_file(directory)),
                    session=FakeSession(),
                    password="password-value",
                )
                benchmark.print_report(report)
            self.assertEqual(code, 0)
            self.assertNotIn("super-secret-token", stdout.getvalue())
            self.assertNotIn("password-value", stdout.getvalue())

    def test_json_sanitizer_removes_sensitive_fields(self):
        payload = benchmark.sanitize(
            {"password": "a", "access_token": "b", "nested": {"authorization": "c", "safe": True}}
        )
        rendered = json.dumps(payload)
        for forbidden in ("password", "access_token", "authorization"):
            self.assertNotIn(forbidden, rendered)
        self.assertTrue(payload["nested"]["safe"])

    def test_defaults_contain_no_container_control(self):
        source = Path(benchmark.__file__).read_text(encoding="utf-8").casefold()
        self.assertNotIn("subprocess", source)
        self.assertNotIn("docker compose down", source)
        self.assertNotIn("docker restart", source)


class BenchmarkStatisticsTests(unittest.TestCase):
    def test_aggregate_mean_median_p50_p95(self):
        stats = benchmark.duration_statistics([1, 2, 3, 100])
        self.assertEqual(stats["mean_ms"], 26.5)
        self.assertEqual(stats["median_ms"], 2.5)
        self.assertEqual(stats["p50_ms"], 2)
        self.assertEqual(stats["p95_ms"], 100)

    def test_cold_and_warm_are_separate(self):
        records = [
            benchmark.RunRecord("search", "f", "cold", 1, "p", 200, 100, True),
            benchmark.RunRecord("search", "f", "warm", 1, "p", 200, 10, True),
        ]
        aggregates = benchmark.aggregate_records(records)
        self.assertEqual(len(aggregates), 2)
        self.assertEqual({item["phase"] for item in aggregates}, {"cold", "warm"})

    def test_expected_terms_are_case_insensitive(self):
        passed, missing = benchmark.quality_check(
            {"results": [{"text": "Code av pour autorisation"}]}, ["AV"]
        )
        self.assertTrue(passed)
        self.assertEqual(missing, [])
        self.assertEqual(
            benchmark.quality_check({"answer": "Autre"}, ["AV"]),
            (False, ["AV"]),
        )

    def test_chat_route_checks_the_answer_only_not_raw_sources(self):
        payload = {
            "answer": "Aucune règle spécifique ne correspond à ce cas.",
            "sources": [{"text": "Si le code erreur est 8, alors PID-1310.8 s'applique."}],
        }
        # Without a route, legacy behavior lets the source text pass the check.
        self.assertEqual(benchmark.quality_check(payload, ["PID-1310"]), (True, []))
        # For chat, the term must appear in the generated answer itself.
        self.assertEqual(
            benchmark.quality_check(payload, ["PID-1310"], route="chat"),
            (False, ["PID-1310"]),
        )
        matching_answer = {"answer": "Le code PID-1310.8 s'applique ici.", "sources": []}
        self.assertEqual(
            benchmark.quality_check(matching_answer, ["PID-1310"], route="chat"),
            (True, []),
        )


class BenchmarkExecutionTests(unittest.TestCase):
    def test_failed_request_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            _report, code = benchmark.run_benchmark(
                args_for(fixture_file(directory)),
                session=FakeSession([500, 200]),
                password="secret",
            )
            self.assertNotEqual(code, 0)

    def test_audit_ids_differ_and_user_is_preserved(self):
        records = [
            benchmark.RunRecord(
                "search", "f", "cold", 1, "pair", 200, 1, True,
                audit_retrieval_id=10, audit_user_id=17,
            ),
            benchmark.RunRecord(
                "search", "f", "warm", 1, "pair", 200, 1, True,
                audit_retrieval_id=11, audit_user_id=17,
            ),
        ]
        self.assertEqual(benchmark.validate_audit_pairs(records, 17), [])
        records[1].audit_retrieval_id = 10
        self.assertIn("reused", benchmark.validate_audit_pairs(records, 17)[0])
        records[1].audit_retrieval_id = 11
        records[1].audit_user_id = 99
        self.assertIn("user id", benchmark.validate_audit_pairs(records, 17)[0])

    def test_cache_unavailable_is_successful_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            report, code = benchmark.run_benchmark(
                args_for(
                    fixture_file(directory),
                    check_cache_status=True,
                    expect_cache_unavailable=True,
                ),
                session=FakeSession(cache_connected=False),
                password="secret",
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["cache_unavailable_validation"]["passed"])
            self.assertTrue(all(run["success"] for run in report["runs"]))

    def test_log_matching_skips_warmups(self):
        records = [
            benchmark.RunRecord("search", "f", "cold", 1, "p", 200, 1, True),
            benchmark.RunRecord("search", "f", "warm", 1, "p", 200, 1, True),
        ]
        events = [
            {"event": "search_performance", "cache_status": "miss", "total_ms": 30},
            {"event": "search_performance", "cache_status": "hit", "total_ms": 20},
            {"event": "search_performance", "cache_status": "hit", "total_ms": 10},
        ]
        benchmark.attach_log_observations(records, events, warmups=1)
        self.assertEqual(records[0].cache_state, "miss")
        self.assertEqual(records[1].cache_state, "hit")
        self.assertEqual(records[1].server_timings_ms["total_ms"], 10)

    def test_offline_mocked_chat_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            report, code = benchmark.run_benchmark(
                args_for(fixture_file(directory), route="chat"),
                session=FakeSession(),
                password="secret",
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(report["runs"]), 2)
            self.assertTrue(all(run["answer_length"] > 0 for run in report["runs"]))


if __name__ == "__main__":
    unittest.main()
