from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import benchmark_ollama_profiles as benchmark


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise benchmark.requests.HTTPError(f"HTTP {self.status_code}")


class FakeApiSession:
    def __init__(self):
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        if url.endswith("/auth/signin"):
            return FakeResponse(
                200,
                {
                    "access_token": "secret-access-token",
                    "user": {"id": 9, "role": "agent"},
                },
            )
        return FakeResponse(
            200,
            {
                "results": [
                    {
                        "rank": rank,
                        "id": f"chunk-{rank}",
                        "article_title": "Article",
                        "section_title": "Section",
                        "text": f"Le code AV est documenté dans la source {rank}.",
                    }
                    for rank in range(1, 6)
                ],
                "audit": {"retrieval_id": 40, "user_id": 9},
            },
        )

    def close(self):
        pass


class FakeOllamaSession:
    def __init__(self, *, status=200, answer="Le code situation est AV."):
        self.status = status
        self.answer = answer
        self.payloads = []

    def post(self, url, json=None, timeout=None):
        self.payloads.append(json)
        return FakeResponse(
            self.status,
            {
                "response": self.answer,
                "done_reason": "stop",
                "prompt_eval_count": 100,
                "eval_count": 20,
                "total_duration": 2_000_000_000,
                "prompt_eval_duration": 400_000_000,
                "eval_duration": 1_500_000_000,
            },
        )

    def close(self):
        pass


def make_files(directory: str) -> tuple[Path, Path]:
    profiles = Path(directory) / "profiles.json"
    profiles.write_text(
        json.dumps(
            [
                {
                    "name": "baseline_3b",
                    "model": "llama3.2:3b",
                    "num_ctx": 4096,
                    "num_predict": 350,
                    "temperature": 0.1,
                    "max_chunks": 5,
                    "max_context_chars": 12000,
                    "concise_instruction": None,
                },
                {
                    "name": "fast_1b",
                    "model": "llama3.2:1b",
                    "num_ctx": 4096,
                    "num_predict": 128,
                    "temperature": 0.1,
                    "max_chunks": 5,
                    "max_context_chars": 12000,
                    "concise_instruction": None,
                },
            ]
        ),
        encoding="utf-8",
    )
    fixtures = Path(directory) / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            [
                {
                    "name": "fixture",
                    "query": "Quel code ?",
                    "rubric": {
                        "grading": "exact_code",
                        "expected_final_codes": ["AV"],
                        "forbidden_final_codes": ["DR"],
                        "require_sources": True,
                        "minimum_answer_characters": 10,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    return profiles, fixtures


def make_args(profiles_path: Path, fixtures: Path, **overrides) -> argparse.Namespace:
    values = {
        "base_url": "http://api.example.invalid",
        "email": "agent@example.invalid",
        "ollama_url": "http://ollama.example.invalid/api/generate",
        "profiles_file": profiles_path,
        "fixtures": fixtures,
        "profiles": "baseline_3b",
        "repetitions": 1,
        "warmups": 0,
        "prediction_limits": None,
        "chunk_counts": None,
        "context_budgets": None,
        "timeout": 30.0,
        "keep_alive": "10m",
        "json_output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class ProfileConfigurationTests(unittest.TestCase):
    def test_baseline_remains_3b_and_is_default(self):
        parser = benchmark.build_parser()
        args = parser.parse_args(["--email", "agent@example.invalid"])
        self.assertEqual(args.profiles, "baseline_3b")
        profiles = benchmark.load_profiles(benchmark.DEFAULT_PROFILES)
        self.assertEqual(profiles["baseline_3b"]["model"], "llama3.2:3b")
        self.assertEqual(profiles["baseline_3b"]["num_predict"], 350)

    def test_fast_1b_requires_explicit_selection(self):
        profiles = benchmark.load_profiles(benchmark.DEFAULT_PROFILES)
        defaults = benchmark.build_experiments(
            benchmark.select_profile_names("baseline_3b", profiles),
            profiles,
        )
        self.assertTrue(all(item.model == "llama3.2:3b" for item in defaults))
        selected = benchmark.build_experiments(
            benchmark.select_profile_names("fast_1b", profiles),
            profiles,
        )
        self.assertEqual(selected[0].model, "llama3.2:1b")

    def test_profile_and_override_settings_are_bounded(self):
        self.assertEqual(
            benchmark.parse_int_list(
                "350,192,128,96", minimum=1, maximum=2048, name="predict"
            ),
            [350, 192, 128, 96],
        )
        with self.assertRaises(ValueError):
            benchmark.parse_int_list("4096", minimum=1, maximum=2048, name="predict")
        with tempfile.TemporaryDirectory() as directory:
            profiles, _fixtures = make_files(directory)
            payload = json.loads(profiles.read_text())
            payload[0]["num_ctx"] = 100
            profiles.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_profiles(profiles)

    def test_prediction_experiments_represent_shorter_limits(self):
        profiles = benchmark.load_profiles(benchmark.DEFAULT_PROFILES)
        experiments = benchmark.build_experiments(
            ["baseline_3b"],
            profiles,
            prediction_limits=[350, 192, 128, 96],
        )
        self.assertEqual(
            [experiment.num_predict for experiment in experiments],
            [350, 192, 128, 96],
        )


class ContextAndQualityTests(unittest.TestCase):
    def setUp(self):
        self.retrieved = [
            {
                "rank": rank,
                "id": f"chunk-{rank}",
                "article_title": "Article",
                "section_title": "Section",
                "text": "Texte " * 30,
            }
            for rank in range(1, 6)
        ]

    def test_context_limit_preserves_ranking_and_records_omissions(self):
        experiment = benchmark.Experiment(
            "baseline_3b", "llama3.2:3b", 4096, 350, 0.1, 3, 12000, None
        )
        _context, selected, included, omitted = benchmark.prepare_evidence(
            self.retrieved, experiment
        )
        self.assertEqual(selected, ["chunk-1", "chunk-2", "chunk-3"])
        self.assertEqual(included, ["chunk-1", "chunk-2", "chunk-3"])
        self.assertEqual(omitted, ["chunk-4", "chunk-5"])

    def evaluate_pp(self, answer, *, evidence="Le code PP est documenté."):
        return benchmark.evaluate_quality(
            answer,
            {
                "grading": "exact_code",
                "expected_final_codes": ["PP"],
                "forbidden_final_codes": ["CP"],
                "require_sources": True,
                "minimum_answer_characters": 2,
            },
            ["chunk-1"],
            source_evidence=evidence,
            done_reason="stop",
            completion_tokens=10,
            num_predict=96,
        )

    def test_wrong_asserted_code_fails_even_if_expected_code_is_mentioned(self):
        result = self.evaluate_pp("Pour le percement PP, le code approprié est CP.")
        self.assertEqual(result["completeness"], "fail")
        self.assertEqual(result["forbidden_recommendations"], ["CP"])

    def test_explicitly_rejected_forbidden_code_does_not_fail(self):
        result = self.evaluate_pp("Utiliser PP, et non CP.")
        self.assertEqual(result["completeness"], "pass")
        self.assertEqual(result["extracted_recommended_codes"], ["PP"])

    def test_alternative_codes_fail_as_conflicting(self):
        result = self.evaluate_pp("PP ou CP")
        self.assertEqual(result["completeness"], "fail")
        self.assertEqual(result["conflicting_codes"], ["PP", "CP"])

    def test_correct_direct_code_passes(self):
        self.assertEqual(self.evaluate_pp("PP")["completeness"], "pass")

    def test_recommendation_phrase_variants_are_extracted(self):
        for answer in (
            "Le code situation PP",
            "Associer PP",
            "Appliquer PP",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    self.evaluate_pp(answer)["extracted_recommended_codes"],
                    ["PP"],
                )

    def test_unknown_recommended_code_fails(self):
        result = self.evaluate_pp("Utiliser ZZ")
        self.assertEqual(result["completeness"], "fail")
        self.assertIn("unexpected recommendation: ZZ", result["quality_reason"])

    def test_procedural_term_presence_is_not_a_full_pass(self):
        result = benchmark.evaluate_quality(
            "FTTH " + "contenu générique " * 4,
            {
                "grading": "procedural",
                "expected_final_codes": ["FTTH"],
                "forbidden_final_codes": [],
                "expected_terms": ["FTTH"],
                "require_sources": True,
                "minimum_answer_characters": 40,
            },
            ["chunk-1"],
            source_evidence="Procédure FTTH documentée.",
            done_reason="stop",
            completion_tokens=20,
            num_predict=96,
        )
        self.assertEqual(result["completeness"], "partial")

    def test_unavailability_claim_fails_when_evidence_contains_answer(self):
        result = self.evaluate_pp("Aucune information ne permet de déterminer le code.")
        self.assertEqual(result["completeness"], "fail")
        self.assertTrue(result["unsupported_unavailability_claims"])

    def test_quality_rubric_detects_forbidden_recommendation_and_truncation(self):
        result = benchmark.evaluate_quality(
            "Utilisez DR",
            {
                "grading": "exact_code",
                "expected_final_codes": ["AV"],
                "forbidden_final_codes": ["DR"],
                "require_sources": True,
                "minimum_answer_characters": 10,
            },
            ["chunk-1"],
            source_evidence="Le code AV est documenté.",
            done_reason="length",
            completion_tokens=96,
            num_predict=96,
        )
        self.assertFalse(result["unsupported_codes_pass"])
        self.assertTrue(result["truncation_warning"])
        self.assertEqual(result["completeness"], "fail")

    def test_answer_review_redacts_tokens_and_passwords(self):
        value = (
            "Bearer abc123 password=hunter2 "
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature"
        )
        redacted = benchmark.redact_text(value)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("eyJhbGci", redacted)


class BenchmarkOutputTests(unittest.TestCase):
    def test_profiles_remain_separate_and_labels_are_correct(self):
        runs = [
            benchmark.ModelRun(
                "baseline_3b", "baseline", "f", 1, "llama3.2:3b",
                4096, 350, 5, 12000, [], [], [], 0, 100, True,
                completeness="pass",
            ),
            benchmark.ModelRun(
                "fast_1b", "fast", "f", 1, "llama3.2:1b",
                4096, 128, 5, 12000, [], [], [], 0, 50, True,
                completeness="partial",
            ),
        ]
        aggregates = benchmark.aggregate_runs(runs)
        self.assertEqual(len(aggregates), 2)
        self.assertEqual(
            {(item["profile"], item["model"]) for item in aggregates},
            {("baseline_3b", "llama3.2:3b"), ("fast_1b", "llama3.2:1b")},
        )
        self.assertEqual(
            {item["quality_pass_rate"] for item in aggregates},
            {0.0, 1.0},
        )

    def test_mocked_profile_comparison_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles, fixtures = make_files(directory)
            args = make_args(
                profiles,
                fixtures,
                profiles="baseline_3b,fast_1b",
                prediction_limits="350,128",
            )
            ollama = FakeOllamaSession()
            report, code = benchmark.run_benchmark(
                args,
                api_session=FakeApiSession(),
                ollama_session=ollama,
                password="benchmark-password",
            )
            rendered = json.dumps(report)
            self.assertEqual(code, 0)
            self.assertEqual({run["model"] for run in report["runs"]}, {
                "llama3.2:3b", "llama3.2:1b",
            })
            self.assertEqual({run["num_predict"] for run in report["runs"]}, {350, 128})
            for forbidden in (
                "benchmark-password",
                "secret-access-token",
                "access_token",
                "ollama.example.invalid",
            ):
                self.assertNotIn(forbidden, rendered)
            output = io.StringIO()
            with redirect_stdout(output):
                benchmark.print_report(report)
            self.assertIn("HUMAN REVIEW", output.getvalue())
            self.assertNotIn("secret-access-token", output.getvalue())

    def test_generation_failure_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles, fixtures = make_files(directory)
            report, code = benchmark.run_benchmark(
                make_args(profiles, fixtures),
                api_session=FakeApiSession(),
                ollama_session=FakeOllamaSession(status=500),
                password="secret",
            )
            self.assertNotEqual(code, 0)
            self.assertFalse(report["runs"][0]["success"])


if __name__ == "__main__":
    unittest.main()
