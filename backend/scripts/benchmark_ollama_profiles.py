#!/usr/bin/env python3
"""Explicit model/configuration benchmark using fixed authenticated retrieval evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.ollama_service import (
    build_context,
    build_grounded_prompt,
    deduplicate_chunks,
)


FIXTURE_DIR = Path(__file__).with_name("fixtures")
DEFAULT_PROFILES = FIXTURE_DIR / "ollama_profiles.json"
DEFAULT_FIXTURES = FIXTURE_DIR / "ollama_quality_queries.json"
BASELINE_PROFILE = "baseline_3b"
FAST_PROFILE_NAMES = {"fast_1b", "fast_1b_concise"}
SENSITIVE_KEYS = {
    "password",
    "access_token",
    "token",
    "authorization",
    "redis_url",
    "ollama_url",
}
TERMINAL_PUNCTUATION = (".", "!", "?", "…", "»", '"', ")", "]")


@dataclass(frozen=True)
class Experiment:
    profile: str
    model: str
    num_ctx: int
    num_predict: int
    temperature: float
    max_chunks: int
    max_context_chars: int
    concise_instruction: str | None

    @property
    def label(self) -> str:
        return (
            f"{self.profile}:chunks={self.max_chunks}:"
            f"context={self.max_context_chars}:predict={self.num_predict}"
        )


@dataclass
class ModelRun:
    profile: str
    experiment: str
    fixture: str
    repetition: int
    model: str
    num_ctx: int
    num_predict: int
    max_chunks: int
    max_context_chars: int
    selected_source_ids: list[str]
    included_source_ids: list[str]
    omitted_source_ids: list[str]
    context_characters: int
    client_duration_ms: float
    success: bool
    error: str | None = None
    ollama_total_ms: float | None = None
    prompt_eval_ms: float | None = None
    generation_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    output_characters: int = 0
    output_token_estimate: int = 0
    tokens_per_second: float | None = None
    expected_terms_pass: bool = False
    missing_expected_terms: list[str] | None = None
    source_presence_pass: bool = False
    unsupported_codes_pass: bool = False
    unsupported_codes_found: list[str] | None = None
    extracted_recommended_codes: list[str] | None = None
    recommended_business_codes: list[str] | None = None
    rejected_alternative_codes: list[str] | None = None
    ignored_identifier_tokens: list[str] | None = None
    conflicting_codes: list[str] | None = None
    forbidden_recommendations: list[str] | None = None
    unsupported_unavailability_claims: list[str] | None = None
    unsafe_procedural_claims: list[str] | None = None
    quality_reason: str = ""
    directly_addresses_question: bool = False
    truncation_warning: bool = False
    completeness: str = "fail"
    answer: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare explicit Ollama profiles using one authenticated retrieval "
            "result per fixture. No service is restarted."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True, help="Admin or agent email.")
    parser.add_argument(
        "--ollama-url",
        default=os.getenv(
            "BENCHMARK_OLLAMA_URL",
            "http://127.0.0.1:11434/api/generate",
        ),
        help="Ollama generate endpoint; omitted from reports.",
    )
    parser.add_argument("--profiles-file", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--profiles",
        default=BASELINE_PROFILE,
        help="Comma-separated explicit profile names. Default: baseline_3b only.",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--prediction-limits",
        help="Optional comma-separated experiment values, e.g. 350,192,128,96.",
    )
    parser.add_argument(
        "--chunk-counts",
        help="Optional comma-separated experiment values, e.g. 5,3.",
    )
    parser.add_argument(
        "--context-budgets",
        help="Optional comma-separated character budgets, e.g. 12000,6000.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--json-output", type=Path)
    return parser


def _validate_http_url(parser: argparse.ArgumentParser, value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error(f"{name} must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error(f"{name} cannot contain credentials, a query, or a fragment")


def parse_int_list(
    value: str | None,
    *,
    minimum: int,
    maximum: int,
    name: str,
) -> list[int] | None:
    if value is None:
        return None
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError(f"{name} must contain only integers") from error
    if not values:
        raise ValueError(f"{name} cannot be empty")
    if any(item < minimum or item > maximum for item in values):
        raise ValueError(f"{name} values must be between {minimum} and {maximum}")
    return list(dict.fromkeys(values))


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    _validate_http_url(parser, args.base_url, "--base-url")
    _validate_http_url(parser, args.ollama_url, "--ollama-url")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds")
    if not args.keep_alive.strip():
        parser.error("--keep-alive cannot be empty")
    try:
        parse_int_list(
            args.prediction_limits,
            minimum=1,
            maximum=2048,
            name="--prediction-limits",
        )
        parse_int_list(
            args.chunk_counts,
            minimum=1,
            maximum=5,
            name="--chunk-counts",
        )
        parse_int_list(
            args.context_budgets,
            minimum=1000,
            maximum=100000,
            name="--context-budgets",
        )
    except ValueError as error:
        parser.error(str(error))


def load_profiles(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("profile file must contain a non-empty JSON list")
    profiles: dict[str, dict[str, Any]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("each profile must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("each profile requires a name")
        if name in profiles:
            raise ValueError(f"duplicate profile: {name}")
        model = raw.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"profile {name} requires a model")
        bounded = {
            "num_ctx": (512, 32768),
            "num_predict": (1, 2048),
            "max_chunks": (1, 5),
            "max_context_chars": (1000, 100000),
        }
        for field, (minimum, maximum) in bounded.items():
            value = raw.get(field)
            if not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(
                    f"profile {name} {field} must be between {minimum} and {maximum}"
                )
        temperature = raw.get("temperature")
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError(f"profile {name} temperature must be between 0 and 2")
        instruction = raw.get("concise_instruction")
        if instruction is not None and not isinstance(instruction, str):
            raise ValueError(f"profile {name} concise_instruction must be text or null")
        profiles[name] = raw
    baseline = profiles.get(BASELINE_PROFILE)
    if not baseline or baseline.get("model") != "llama3.2:3b":
        raise ValueError("baseline_3b must explicitly use llama3.2:3b")
    return profiles


def select_profile_names(raw: str, profiles: dict[str, dict[str, Any]]) -> list[str]:
    names = list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not names:
        raise ValueError("--profiles cannot be empty")
    unknown = [name for name in names if name not in profiles]
    if unknown:
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}")
    return names


def build_experiments(
    selected_names: list[str],
    profiles: dict[str, dict[str, Any]],
    *,
    prediction_limits: list[int] | None = None,
    chunk_counts: list[int] | None = None,
    context_budgets: list[int] | None = None,
) -> list[Experiment]:
    experiments = []
    for name in selected_names:
        profile = profiles[name]
        predictions = prediction_limits or [profile["num_predict"]]
        chunks = chunk_counts or [profile["max_chunks"]]
        budgets = context_budgets or [profile["max_context_chars"]]
        for prediction in predictions:
            for chunk_count in chunks:
                for budget in budgets:
                    experiments.append(
                        Experiment(
                            profile=name,
                            model=profile["model"],
                            num_ctx=profile["num_ctx"],
                            num_predict=prediction,
                            temperature=float(profile["temperature"]),
                            max_chunks=chunk_count,
                            max_context_chars=budget,
                            concise_instruction=profile.get("concise_instruction"),
                        )
                    )
    return experiments


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("quality fixture file must contain a non-empty JSON list")
    fixtures = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("each fixture must be an object")
        name, query, rubric = raw.get("name"), raw.get("query"), raw.get("rubric")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each fixture requires a name")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"fixture {name!r} requires a query")
        if not isinstance(rubric, dict):
            raise ValueError(f"fixture {name!r} requires a rubric")
        expected_codes = rubric.get("expected_final_codes")
        forbidden_codes = rubric.get("forbidden_final_codes")
        allowed_codes = rubric.get("allowed_codes", [])
        expected = rubric.get("expected_terms", [])
        forbidden_claims = rubric.get("forbidden_claims", [])
        minimum = rubric.get("minimum_answer_characters", 1)
        if not isinstance(expected_codes, list):
            raise ValueError(f"fixture {name!r} requires expected_final_codes")
        if not isinstance(forbidden_codes, list):
            raise ValueError(f"fixture {name!r} requires forbidden_final_codes")
        if not isinstance(allowed_codes, list):
            raise ValueError(f"fixture {name!r} allowed_codes must be a list")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in (
                expected_codes
                + forbidden_codes
                + allowed_codes
                + expected
                + forbidden_claims
            )
        ):
            raise ValueError(f"fixture {name!r} rubric terms must be strings")
        if rubric.get("grading", "exact_code") not in {"exact_code", "procedural"}:
            raise ValueError(f"fixture {name!r} has invalid grading")
        if not isinstance(rubric.get("require_sources"), bool):
            raise ValueError(f"fixture {name!r} require_sources must be boolean")
        if not isinstance(minimum, int) or not 1 <= minimum <= 10000:
            raise ValueError(f"fixture {name!r} minimum answer length is invalid")
        fixtures.append(raw)
    return fixtures


def _source_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("external_chunk_id") or "unknown")


def prepare_evidence(
    retrieved: list[dict[str, Any]],
    experiment: Experiment,
) -> tuple[str, list[str], list[str], list[str]]:
    ranked = deduplicate_chunks(retrieved, max_chunks=5)
    selected = deduplicate_chunks(ranked, max_chunks=experiment.max_chunks)
    context = build_context(
        selected,
        max_chunks=experiment.max_chunks,
        max_chars=experiment.max_context_chars,
    )
    selected_ids = [_source_id(item) for item in selected]
    included_ids = [
        source_id
        for source_id in selected_ids
        if f"Source ID: {source_id}\n" in context
    ]
    omitted_ids = [
        _source_id(item)
        for item in ranked
        if _source_id(item) not in included_ids
    ]
    return context, selected_ids, included_ids, omitted_ids


def build_benchmark_prompt(
    question: str,
    retrieved: list[dict[str, Any]],
    context: str,
    concise_instruction: str | None,
) -> str:
    prompt = build_grounded_prompt(question, retrieved, context=context)
    if concise_instruction:
        prompt += f"\n\nCONTRAINTE DE BENCHMARK :\n{concise_instruction}"
    return prompt


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[REDACTED_TOKEN]",
        value,
    )
    value = re.sub(
        r"(?i)(password|mot de passe)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    return value


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if key.casefold() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def authenticate(
    session: requests.Session,
    base_url: str,
    email: str,
    password: str,
    timeout: float,
) -> tuple[str, int]:
    response = session.post(
        base_url.rstrip("/") + "/api/v1/auth/signin",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    user_id = payload.get("user", {}).get("id")
    if not isinstance(token, str) or not token:
        raise ValueError("signin response did not contain an access token")
    if not isinstance(user_id, int):
        raise ValueError("signin response did not contain a valid user id")
    return token, user_id


def retrieve_evidence(
    session: requests.Session,
    base_url: str,
    fixture: dict[str, Any],
    user_id: int,
    timeout: float,
) -> list[dict[str, Any]]:
    response = session.post(
        base_url.rstrip("/") + "/api/v1/search",
        json={"query": fixture["query"], "limit": 5},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results")
    audit = payload.get("audit", {})
    if not isinstance(results, list) or not results:
        raise ValueError(f"fixture {fixture['name']} returned no retrieval evidence")
    if audit.get("retrieval_id") is None or audit.get("user_id") != user_id:
        raise ValueError(f"fixture {fixture['name']} retrieval audit attribution failed")
    return results


def _nanoseconds_to_ms(value: Any) -> float | None:
    return float(value) / 1_000_000 if isinstance(value, (int, float)) else None


def _extract_recommendation_codes(
    answer: str,
    business_codes: list[str],
) -> tuple[list[str], list[str]]:
    """Return asserted business codes and explicitly rejected alternatives."""
    cue = re.compile(
        r"(?i)\b(?:utilis(?:er|ez|e)|associer|appliqu(?:er|ez|e|able)|"
        r"choisir|retenir|recommand(?:er|é|ée)|code(?:\s+situation)?"
        r"(?:\s+\w+){0,4}\s+(?:est|sera|:))\b"
    )
    alternative = re.compile(r"(?i)\b(?:ou|soit)\b|/")
    recommended: list[str] = []
    rejected: list[str] = []
    for code in business_codes:
        code_pattern = rf"(?<![\w-]){re.escape(code)}(?![\w-])"
        for match in re.finditer(code_pattern, answer, re.IGNORECASE):
            before = answer[max(0, match.start() - 100) : match.start()]
            after = answer[match.end() : match.end() + 50]
            if re.search(
                r"(?i)(?:\bnon\b|\bpas\b|\bplutôt\s+que)"
                r"\s*[,():-]*\s*$",
                before,
            ):
                rejected.append(code)
                continue
            left = max(answer.rfind(mark, 0, match.start()) for mark in ".!?\n")
            ends = [
                position
                for mark in ".!?\n"
                if (position := answer.find(mark, match.end())) >= 0
            ]
            sentence = answer[left + 1 : min(ends, default=len(answer))]
            direct = answer.strip().casefold().rstrip(".") == code.casefold()
            choice = alternative.search(before[-16:] + after[:16])
            code_situation_prefix = re.search(
                r"(?i)\bcode\s+situation\s*[:=-]?\s*$",
                before,
            )
            if direct or cue.search(sentence) or choice or code_situation_prefix:
                recommended.append(code)
                break
    return list(dict.fromkeys(recommended)), list(dict.fromkeys(rejected))


def _ignored_identifier_tokens(answer: str) -> list[str]:
    ignored: list[str] = []
    identifier_patterns = (
        r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?:::[A-Z0-9]+)*(?![\w-])",
        r"(?<!\w)\d{4,}(?!\w)",
    )
    for pattern in identifier_patterns:
        ignored.extend(match.group(0) for match in re.finditer(pattern, answer))
    non_business = {"FTTH", "RETAIL", "WHOLESALE", "FDE", "ACCES", "SERVICE"}
    ignored.extend(
        token
        for token in re.findall(r"(?<![\w-])[A-Z]{2,}(?![\w-])", answer)
        if token in non_business
    )
    return list(dict.fromkeys(ignored))


def _unavailability_claims(answer: str) -> list[str]:
    patterns = {
        "information unavailable": r"(?i)\b(?:information|source|document|contexte|donnée)s?\b.{0,45}\b(?:indisponible|absent|manqu|introuvable|ne (?:contient|précise|permet)|n['’]est pas (?:présent|fourni))",
        "no information exists": r"(?i)\b(?:aucune information|pas d['’]information|impossible (?:de|à) (?:déterminer|répondre))\b",
    }
    return [label for label, pattern in patterns.items() if re.search(pattern, answer)]


def _unsafe_procedural_claims(answer: str, source_evidence: str) -> list[str]:
    evidence_requires_validation = bool(
        re.search(r"(?i)\b(?:validation|valider|vérification|vérifier)\b", source_evidence)
    )
    denies_validation = bool(
        re.search(
            r"(?i)(?:validation|vérification).{0,30}(?:inutile|facultative|"
            r"pas nécessaire|non nécessaire)|(?:inutile|pas nécessaire|aucun besoin)"
            r".{0,30}(?:valider|vérifier)",
            answer,
        )
    )
    return ["validation declared unnecessary despite source requirement"] if (
        evidence_requires_validation and denies_validation
    ) else []


def evaluate_quality(
    answer: str,
    rubric: dict[str, Any],
    included_source_ids: list[str],
    *,
    source_evidence: str = "",
    done_reason: str | None,
    completion_tokens: int | None,
    num_predict: int,
) -> dict[str, Any]:
    folded = answer.casefold()
    grading = rubric.get("grading", "exact_code")
    expected_codes = rubric.get("expected_final_codes", [])
    forbidden_codes = rubric.get("forbidden_final_codes", [])
    allowed_codes = rubric.get("allowed_codes", [])
    business_codes = list(
        dict.fromkeys(expected_codes + forbidden_codes + allowed_codes)
    )
    expected_terms = rubric.get("expected_terms", [])
    missing = [term for term in expected_terms if term.casefold() not in folded]
    recommended, rejected = _extract_recommendation_codes(answer, business_codes)
    ignored_identifiers = _ignored_identifier_tokens(answer)
    forbidden = [code for code in recommended if code in forbidden_codes]
    unexpected = [code for code in recommended if code not in expected_codes]
    conflicting = recommended if len(recommended) > 1 else []
    unavailable = _unavailability_claims(answer)
    evidence_has_answer = bool(source_evidence) and any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", source_evidence, re.I)
        for term in expected_codes + expected_terms
    )
    unsupported_unavailability = unavailable if evidence_has_answer else []
    forbidden_claims = [
        claim
        for claim in rubric.get("forbidden_claims", [])
        if claim.casefold() in folded
    ]
    unsafe_claims = (
        _unsafe_procedural_claims(answer, source_evidence)
        if grading == "procedural"
        else []
    )
    source_pass = not rubric.get("require_sources") or bool(included_source_ids)
    direct = (
        len(answer.strip()) >= rubric.get("minimum_answer_characters", 1)
        and not unavailable
        and "pas pu générer" not in folded
    )
    truncation = done_reason in {"length", "max_tokens"}
    if (
        completion_tokens is not None
        and completion_tokens >= num_predict
        and answer.strip()
        and not answer.rstrip().endswith(TERMINAL_PUNCTUATION)
    ):
        truncation = True
    if grading == "procedural" and answer.strip():
        visibly_incomplete = bool(
            re.search(r"(?i)(?:[-'’]|\b(?:et|ou|de|du|des|la|le|un|une|pour|avec))$", answer.strip())
        ) or not answer.rstrip().endswith(TERMINAL_PUNCTUATION)
        truncation = truncation or visibly_incomplete

    failures = []
    if grading == "exact_code":
        if not any(code in expected_codes for code in recommended):
            failures.append("no expected code was recommended")
        if forbidden:
            failures.append(f"forbidden recommendation: {', '.join(forbidden)}")
        if unexpected:
            failures.append(f"unexpected recommendation: {', '.join(unexpected)}")
        if conflicting:
            failures.append(f"conflicting recommendations: {', '.join(conflicting)}")
    if unsupported_unavailability:
        failures.append("claims the answer is unavailable despite source evidence")
    if forbidden_claims:
        failures.append(f"forbidden claim: {', '.join(forbidden_claims)}")
    if unsafe_claims:
        failures.extend(unsafe_claims)

    checks = [not missing, source_pass, direct, not truncation]
    if failures:
        completeness = "fail"
    elif grading == "procedural":
        completeness = "partial" if direct and source_pass else "fail"
    elif all(checks):
        completeness = "pass"
    elif direct and source_pass:
        completeness = "partial"
    else:
        completeness = "fail"
    if failures:
        reason = "; ".join(failures)
    elif grading == "procedural":
        reason = (
            "procedural fixture requires substantive human review; term presence is not a full pass"
        )
        if truncation:
            reason += "; output appears truncated"
    elif completeness == "pass":
        reason = "all rubric checks passed"
    else:
        reason = "one or more completeness checks were not satisfied"
    return {
        "expected_terms_pass": not missing,
        "missing_expected_terms": missing,
        "source_presence_pass": source_pass,
        "unsupported_codes_pass": not forbidden,
        "unsupported_codes_found": forbidden,
        "extracted_recommended_codes": recommended,
        "recommended_business_codes": recommended,
        "rejected_alternative_codes": rejected,
        "ignored_identifier_tokens": ignored_identifiers,
        "conflicting_codes": conflicting,
        "forbidden_recommendations": forbidden,
        "unsupported_unavailability_claims": unsupported_unavailability,
        "unsafe_procedural_claims": unsafe_claims,
        "quality_reason": reason,
        "directly_addresses_question": direct,
        "truncation_warning": truncation,
        "completeness": completeness,
    }


def execute_generation(
    session: requests.Session,
    *,
    ollama_url: str,
    experiment: Experiment,
    fixture: dict[str, Any],
    retrieved: list[dict[str, Any]],
    repetition: int,
    keep_alive: str,
    timeout: float,
    clock: Callable[[], float] = time.perf_counter,
) -> ModelRun:
    context, selected_ids, included_ids, omitted_ids = prepare_evidence(
        retrieved,
        experiment,
    )
    prompt = build_benchmark_prompt(
        fixture["query"],
        retrieved,
        context,
        experiment.concise_instruction,
    )
    started = clock()
    try:
        response = session.post(
            ollama_url,
            json={
                "model": experiment.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": keep_alive,
                "options": {
                    "temperature": experiment.temperature,
                    "top_p": 0.9,
                    "num_ctx": experiment.num_ctx,
                    "num_predict": experiment.num_predict,
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        answer = str(payload.get("response") or "").strip()
        if not answer:
            raise ValueError("Ollama returned an empty answer")
        duration_ms = (clock() - started) * 1000
        completion_tokens = payload.get("eval_count")
        completion_tokens = (
            int(completion_tokens)
            if isinstance(completion_tokens, (int, float))
            else None
        )
        generation_ns = payload.get("eval_duration")
        tokens_per_second = None
        if (
            completion_tokens is not None
            and isinstance(generation_ns, (int, float))
            and generation_ns > 0
        ):
            tokens_per_second = completion_tokens / (generation_ns / 1_000_000_000)
        quality = evaluate_quality(
            answer,
            fixture["rubric"],
            included_ids,
            source_evidence=context,
            done_reason=payload.get("done_reason"),
            completion_tokens=completion_tokens,
            num_predict=experiment.num_predict,
        )
        return ModelRun(
            profile=experiment.profile,
            experiment=experiment.label,
            fixture=fixture["name"],
            repetition=repetition,
            model=experiment.model,
            num_ctx=experiment.num_ctx,
            num_predict=experiment.num_predict,
            max_chunks=experiment.max_chunks,
            max_context_chars=experiment.max_context_chars,
            selected_source_ids=selected_ids,
            included_source_ids=included_ids,
            omitted_source_ids=omitted_ids,
            context_characters=len(context),
            client_duration_ms=duration_ms,
            success=True,
            ollama_total_ms=_nanoseconds_to_ms(payload.get("total_duration")),
            prompt_eval_ms=_nanoseconds_to_ms(payload.get("prompt_eval_duration")),
            generation_ms=_nanoseconds_to_ms(generation_ns),
            prompt_tokens=payload.get("prompt_eval_count"),
            completion_tokens=completion_tokens,
            output_characters=len(answer),
            output_token_estimate=completion_tokens or math.ceil(len(answer) / 4),
            tokens_per_second=tokens_per_second,
            answer=redact_text(answer),
            **quality,
        )
    except Exception as error:
        return ModelRun(
            profile=experiment.profile,
            experiment=experiment.label,
            fixture=fixture["name"],
            repetition=repetition,
            model=experiment.model,
            num_ctx=experiment.num_ctx,
            num_predict=experiment.num_predict,
            max_chunks=experiment.max_chunks,
            max_context_chars=experiment.max_context_chars,
            selected_source_ids=selected_ids,
            included_source_ids=included_ids,
            omitted_source_ids=omitted_ids,
            context_characters=len(context),
            client_duration_ms=(clock() - started) * 1000,
            success=False,
            error=f"{type(error).__name__}: {error}",
        )


def nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    samples = sorted(float(value) for value in values)
    if not samples:
        return None
    return samples[max(1, math.ceil(percentile / 100 * len(samples))) - 1]


def aggregate_runs(runs: Iterable[ModelRun]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[ModelRun]] = {}
    for run in runs:
        groups.setdefault((run.profile, run.experiment, run.fixture), []).append(run)
    aggregates = []
    for (profile, experiment, fixture), group in sorted(groups.items()):
        successful = [run for run in group if run.success]
        durations = [run.client_duration_ms for run in successful]
        token_rates = [
            run.tokens_per_second
            for run in successful
            if run.tokens_per_second is not None
        ]
        aggregates.append(
            {
                "profile": profile,
                "experiment": experiment,
                "fixture": fixture,
                "model": group[0].model,
                "num_predict": group[0].num_predict,
                "max_chunks": group[0].max_chunks,
                "max_context_chars": group[0].max_context_chars,
                "minimum_ms": min(durations) if durations else None,
                "maximum_ms": max(durations) if durations else None,
                "mean_ms": statistics.fmean(durations) if durations else None,
                "median_ms": statistics.median(durations) if durations else None,
                "p50_ms": nearest_rank(durations, 50),
                "p95_ms": nearest_rank(durations, 95),
                "mean_tokens_per_second": (
                    statistics.fmean(token_rates) if token_rates else None
                ),
                "successful_requests": len(successful),
                "failed_requests": len(group) - len(successful),
                "quality_pass_rate": (
                    sum(run.completeness == "pass" for run in successful)
                    / len(successful)
                    if successful
                    else None
                ),
                "partial_count": sum(
                    run.completeness == "partial" for run in successful
                ),
                "quality_fail_count": sum(
                    run.completeness == "fail" for run in successful
                ),
            }
        )
    return aggregates


def build_report(
    args: argparse.Namespace,
    experiments: list[Experiment],
    runs: list[ModelRun],
    user_id: int,
) -> dict[str, Any]:
    return sanitize(
        {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "benchmark_kind": "controlled_ollama_profile_comparison",
                "percentile_method": "nearest-rank",
                "authenticated_retrieval_user_id": user_id,
                "quality_notice": "Automated checks are smoke tests; human review is required.",
            },
            "configuration": {
                "base_url": args.base_url,
                "email": args.email,
                "profiles": [experiment.profile for experiment in experiments],
                "repetitions": args.repetitions,
                "warmups": args.warmups,
                "keep_alive": args.keep_alive,
                "timeout_seconds": args.timeout,
            },
            "experiments": [asdict(experiment) for experiment in experiments],
            "runs": [asdict(run) for run in runs],
            "aggregates": aggregate_runs(runs),
        }
    )


def print_report(report: dict[str, Any]) -> None:
    print("Controlled Ollama profile benchmark")
    print("Automated quality checks are smoke tests; compare every answer manually.")
    for aggregate in report["aggregates"]:
        mean = aggregate["mean_ms"]
        latency = "n/a" if mean is None else f"{mean / 1000:.3f}s"
        quality = aggregate["quality_pass_rate"]
        quality_text = "n/a" if quality is None else f"{quality * 100:.1f}%"
        print(
            f"{aggregate['profile']} | {aggregate['fixture']} | "
            f"predict={aggregate['num_predict']} chunks={aggregate['max_chunks']} "
            f"context={aggregate['max_context_chars']} | "
            f"mean={latency} quality-pass={quality_text}"
        )
    print("\nHUMAN REVIEW — ANSWERS")
    for run in report["runs"]:
        print(
            f"\n[{run['profile']} | {run['fixture']} | repetition {run['repetition']} | "
            f"{run['completeness'].upper()}]"
        )
        print(run["answer"] if run["answer"] else f"<generation failed: {run['error']}>")
        print(f"Included sources: {', '.join(run['included_source_ids']) or 'none'}")
        print(f"Omitted sources: {', '.join(run['omitted_source_ids']) or 'none'}")
        print(f"Recommended business codes: {', '.join(run['recommended_business_codes'] or []) or 'none'}")
        print(f"Rejected alternative codes: {', '.join(run['rejected_alternative_codes'] or []) or 'none'}")
        print(f"Ignored identifier tokens: {', '.join(run['ignored_identifier_tokens'] or []) or 'none'}")
        print(f"Conflicting codes: {', '.join(run['conflicting_codes'] or []) or 'none'}")
        print(f"Forbidden recommendations: {', '.join(run['forbidden_recommendations'] or []) or 'none'}")
        print(f"Unsupported unavailability claims: {', '.join(run['unsupported_unavailability_claims'] or []) or 'none'}")
        print(f"Reason: {run['quality_reason'] or run['error'] or 'not evaluated'}")


def new_ollama_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def run_benchmark(
    args: argparse.Namespace,
    *,
    api_session: requests.Session | None = None,
    ollama_session: requests.Session | None = None,
    password: str | None = None,
) -> tuple[dict[str, Any], int]:
    api = api_session or requests.Session()
    ollama = ollama_session or new_ollama_session()
    owns_api = api_session is None
    owns_ollama = ollama_session is None
    token: str | None = None
    secret = password if password is not None else os.getenv("BENCHMARK_PASSWORD")
    if not secret:
        raise ValueError("BENCHMARK_PASSWORD is required")
    try:
        profiles = load_profiles(args.profiles_file)
        selected = select_profile_names(args.profiles, profiles)
        experiments = build_experiments(
            selected,
            profiles,
            prediction_limits=parse_int_list(
                args.prediction_limits,
                minimum=1,
                maximum=2048,
                name="--prediction-limits",
            ),
            chunk_counts=parse_int_list(
                args.chunk_counts,
                minimum=1,
                maximum=5,
                name="--chunk-counts",
            ),
            context_budgets=parse_int_list(
                args.context_budgets,
                minimum=1000,
                maximum=100000,
                name="--context-budgets",
            ),
        )
        fixtures = load_fixtures(args.fixtures)
        token, user_id = authenticate(
            api,
            args.base_url,
            args.email,
            secret,
            args.timeout,
        )
        api.headers.update({"Authorization": f"Bearer {token}"})
        evidence = {
            fixture["name"]: retrieve_evidence(
                api,
                args.base_url,
                fixture,
                user_id,
                args.timeout,
            )
            for fixture in fixtures
        }
        runs: list[ModelRun] = []
        for experiment in experiments:
            for fixture in fixtures:
                for _ in range(args.warmups):
                    execute_generation(
                        ollama,
                        ollama_url=args.ollama_url,
                        experiment=experiment,
                        fixture=fixture,
                        retrieved=evidence[fixture["name"]],
                        repetition=0,
                        keep_alive=args.keep_alive,
                        timeout=args.timeout,
                    )
                for repetition in range(1, args.repetitions + 1):
                    runs.append(
                        execute_generation(
                            ollama,
                            ollama_url=args.ollama_url,
                            experiment=experiment,
                            fixture=fixture,
                            retrieved=evidence[fixture["name"]],
                            repetition=repetition,
                            keep_alive=args.keep_alive,
                            timeout=args.timeout,
                        )
                    )
        report = build_report(args, experiments, runs, user_id)
        failed = any(not run.success for run in runs)
        quality_failed = any(run.completeness == "fail" for run in runs)
        return report, 1 if failed or quality_failed else 0
    finally:
        api.headers.pop("Authorization", None)
        token = None
        secret = None
        if owns_api:
            api.close()
        if owns_ollama:
            ollama.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        report, exit_code = run_benchmark(args)
        print_report(report)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return exit_code
    except (OSError, ValueError, requests.RequestException) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
