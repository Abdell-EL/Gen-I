#!/usr/bin/env python3
"""Opt-in HTTP benchmark for Lab IA Genius retrieval and chat routes."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import requests


DEFAULT_FIXTURES = Path(__file__).with_name("fixtures") / "performance_queries.json"
ROUTE_PATHS = {
    "search": "/api/v1/search",
    "keyword-search": "/api/v1/keyword-search",
    "chat": "/api/v1/chat",
}
PERFORMANCE_EVENTS = {
    "search": "search_performance",
    "keyword-search": "keyword_search_performance",
    "chat": "chat_performance",
}
HIT_STATES = {"hit", "hit_after_lock", "hit_after_wait"}
MISS_STATES = {"miss", "corrupt"}
UNAVAILABLE_STATES = {"unavailable", "disabled"}
SENSITIVE_FIELDS = {
    "password",
    "access_token",
    "token",
    "authorization",
    "redis_url",
    "raw_cache_key",
}


@dataclass
class RunRecord:
    route: str
    fixture: str
    phase: str
    repetition: int
    pair_id: str
    http_status: int | None
    duration_ms: float
    success: bool
    error: str | None = None
    cache_state: str = "not_observed"
    retrieval_cache_status: str | None = None
    embedding_cache_status: str | None = None
    result_count: int | None = None
    top_score: float | None = None
    answer_length: int | None = None
    quality_pass: bool | None = None
    missing_expected_terms: list[str] | None = None
    audit_retrieval_id: int | None = None
    audit_user_id: int | None = None
    audit_session_id: int | None = None
    audit_message_id: int | None = None
    server_timings_ms: dict[str, float] | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an explicit cold/warm Lab IA Genius API benchmark.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True, help="Admin or agent email.")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--route",
        choices=("search", "keyword-search", "chat", "all"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--check-cache-status",
        action="store_true",
        help="Call the existing admin-only safe cache status endpoint.",
    )
    parser.add_argument(
        "--performance-log",
        type=Path,
        help="Optional local structured server log used to attach internal timings.",
    )
    parser.add_argument(
        "--expect-cache-unavailable",
        action="store_true",
        help="Require observed disabled/unavailable cache while API calls still succeed.",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    parsed = urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("--base-url must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--base-url cannot contain credentials, a query, or a fragment")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.warmups < 0:
        parser.error("--warmups cannot be negative")
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be between 1 and 20")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.expect_cache_unavailable and not (
        args.check_cache_status or args.performance_log
    ):
        parser.error(
            "--expect-cache-unavailable requires --check-cache-status "
            "or --performance-log so the state can be verified"
        )


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("fixture file must contain a non-empty JSON list")
    fixtures: list[dict[str, Any]] = []
    for index, fixture in enumerate(payload):
        if not isinstance(fixture, dict):
            raise ValueError(f"fixture {index} must be an object")
        name, query = fixture.get("name"), fixture.get("query")
        routes = fixture.get("routes", [])
        terms = fixture.get("expected_terms", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"fixture {index} has no valid name")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"fixture {name!r} has no valid query")
        if not isinstance(routes, list) or not routes:
            raise ValueError(f"fixture {name!r} has no routes")
        if any(route not in ROUTE_PATHS for route in routes):
            raise ValueError(f"fixture {name!r} contains an unknown route")
        if not isinstance(terms, list) or any(not isinstance(term, str) for term in terms):
            raise ValueError(f"fixture {name!r} has invalid expected_terms")
        fixtures.append(
            {
                "name": name.strip(),
                "query": query.strip(),
                "routes": list(dict.fromkeys(routes)),
                "expected_terms": terms,
            }
        )
    return fixtures


def nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return ordered[rank - 1]


def duration_statistics(values: Iterable[float]) -> dict[str, float | None]:
    samples = list(values)
    if not samples:
        return {
            "minimum_ms": None,
            "maximum_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }
    return {
        "minimum_ms": min(samples),
        "maximum_ms": max(samples),
        "mean_ms": statistics.fmean(samples),
        "median_ms": statistics.median(samples),
        "p50_ms": nearest_rank(samples, 50),
        "p95_ms": nearest_rank(samples, 95),
    }


def aggregate_records(records: Iterable[RunRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[RunRecord]] = {}
    for record in records:
        groups.setdefault((record.route, record.fixture, record.phase), []).append(record)
    aggregates = []
    for (route, fixture, phase), group in sorted(groups.items()):
        successful = [record for record in group if record.success]
        stats = duration_statistics(record.duration_ms for record in successful)
        hit_count = sum(record.cache_state == "hit" for record in group)
        miss_count = sum(record.cache_state == "miss" for record in group)
        aggregates.append(
            {
                "route": route,
                "fixture": fixture,
                "phase": phase,
                **stats,
                "successful_requests": len(successful),
                "failed_requests": len(group) - len(successful),
                "cache_hit_count": hit_count,
                "cache_miss_count": miss_count,
                "cache_unavailable_count": sum(
                    record.cache_state == "unavailable" for record in group
                ),
                "cache_not_observed_count": sum(
                    record.cache_state == "not_observed" for record in group
                ),
            }
        )
    return aggregates


def quality_check(
    payload: dict[str, Any],
    terms: list[str],
    *,
    route: str | None = None,
) -> tuple[bool | None, list[str]]:
    if not terms:
        return None, []
    parts: list[str] = []
    if route == "chat":
        # The chat route's real "answer" is the generated text alone.
        # Checking it against the retrieved sources too would let a term
        # "pass" just because a source chunk happens to contain it, even
        # when the model never used that chunk or reached a different
        # conclusion — hiding exactly the kind of failure worth catching.
        answer = payload.get("answer")
        if isinstance(answer, str):
            parts.append(answer)
    else:
        for key in ("answer", "query", "question"):
            value = payload.get(key)
            if isinstance(value, str):
                parts.append(value)
        for key in ("results", "sources"):
            for item in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                if isinstance(item, dict):
                    parts.extend(
                        str(item.get(field, ""))
                        for field in ("id", "kb_code", "article_title", "section_title", "text")
                    )
    combined = "\n".join(parts).casefold()
    missing = [term for term in terms if term.casefold() not in combined]
    return not missing, missing


def make_payload(route: str, query: str, limit: int) -> dict[str, Any]:
    if route == "chat":
        return {"question": query}
    return {"query": query, "limit": limit}


def summarize_payload(payload: dict[str, Any], route: str) -> dict[str, Any]:
    items_key = "sources" if route == "chat" else "results"
    items = payload.get(items_key)
    items = items if isinstance(items, list) else []
    top_score = items[0].get("score") if items and isinstance(items[0], dict) else None
    audit = payload.get("audit") if isinstance(payload.get("audit"), dict) else {}
    return {
        "result_count": len(items),
        "top_score": float(top_score) if isinstance(top_score, (int, float)) else None,
        "answer_length": len(payload.get("answer", "")) if route == "chat" else None,
        "audit_retrieval_id": audit.get("retrieval_id"),
        "audit_user_id": audit.get("user_id"),
        "audit_session_id": audit.get("session_id"),
        "audit_message_id": audit.get("message_id"),
    }


def perform_request(
    session: requests.Session,
    *,
    base_url: str,
    route: str,
    fixture: dict[str, Any],
    query: str,
    phase: str,
    repetition: int,
    pair_id: str,
    limit: int,
    timeout: float,
    clock: Callable[[], float] = time.perf_counter,
) -> RunRecord:
    started = clock()
    response = None
    try:
        response = session.post(
            base_url.rstrip("/") + ROUTE_PATHS[route],
            json=make_payload(route, query, limit),
            timeout=timeout,
        )
        elapsed = (clock() - started) * 1000
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            raise ValueError("response body is not a JSON object")
        success = 200 <= response.status_code < 300
        quality_pass, missing_terms = quality_check(
            payload,
            fixture["expected_terms"],
            route=route,
        )
        summary = summarize_payload(payload, route) if success else {}
        return RunRecord(
            route=route,
            fixture=fixture["name"],
            phase=phase,
            repetition=repetition,
            pair_id=pair_id,
            http_status=response.status_code,
            duration_ms=elapsed,
            success=success,
            error=None if success else f"HTTP {response.status_code}",
            quality_pass=quality_pass if success else None,
            missing_expected_terms=missing_terms if success else None,
            **summary,
        )
    except Exception as error:
        return RunRecord(
            route=route,
            fixture=fixture["name"],
            phase=phase,
            repetition=repetition,
            pair_id=pair_id,
            http_status=getattr(response, "status_code", None),
            duration_ms=(clock() - started) * 1000,
            success=False,
            error=f"{type(error).__name__}: {error}",
        )


def authenticate(
    session: requests.Session,
    base_url: str,
    email: str,
    password: str,
    timeout: float,
) -> tuple[str, int, str]:
    response = session.post(
        base_url.rstrip("/") + "/api/v1/auth/signin",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    user = payload.get("user", {})
    if not isinstance(token, str) or not token:
        raise ValueError("signin response did not contain an access token")
    if not isinstance(user.get("id"), int):
        raise ValueError("signin response did not contain a valid user id")
    return token, user["id"], str(user.get("role", "unknown"))


def read_log_events(path: Path, offset: int) -> list[dict[str, Any]]:
    events = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        for line in handle:
            brace = line.find("{")
            if brace < 0:
                continue
            try:
                payload = json.loads(line[brace:])
            except json.JSONDecodeError:
                continue
            if payload.get("event") in PERFORMANCE_EVENTS.values():
                events.append(payload)
    return events


def attach_log_observations(
    records: list[RunRecord],
    events: list[dict[str, Any]],
    warmups: int = 0,
) -> None:
    remaining = list(events)
    for record in records:
        expected = PERFORMANCE_EVENTS[record.route]
        if record.phase == "warm":
            for _ in range(warmups):
                skipped_index = next(
                    (
                        index
                        for index, event in enumerate(remaining)
                        if event.get("event") == expected
                    ),
                    None,
                )
                if skipped_index is not None:
                    remaining.pop(skipped_index)
        event_index = next(
            (index for index, event in enumerate(remaining) if event.get("event") == expected),
            None,
        )
        if event_index is None:
            continue
        event = remaining.pop(event_index)
        retrieval = event.get("cache_status")
        embedding = event.get("embedding_cache_status")
        record.retrieval_cache_status = retrieval if isinstance(retrieval, str) else None
        record.embedding_cache_status = embedding if isinstance(embedding, str) else None
        observed = {record.retrieval_cache_status, record.embedding_cache_status}
        if observed & UNAVAILABLE_STATES:
            record.cache_state = "unavailable"
        elif record.retrieval_cache_status in HIT_STATES:
            record.cache_state = "hit"
        elif record.retrieval_cache_status in MISS_STATES:
            record.cache_state = "miss"
        timings = {}
        for field in (
            "total_ms",
            "embedding_ms",
            "milvus_ms",
            "postgres_ms",
            "ollama_ms",
            "audit_ms",
            "cache_lookup_ms",
        ):
            value = event.get(field)
            if isinstance(value, (int, float)):
                timings[field] = float(value)
        record.server_timings_ms = timings or None


def validate_audit_pairs(records: Iterable[RunRecord], expected_user_id: int) -> list[str]:
    errors = []
    groups: dict[str, list[RunRecord]] = {}
    for record in records:
        if record.success:
            groups.setdefault(record.pair_id, []).append(record)
    for pair_id, pair in groups.items():
        cold = next((record for record in pair if record.phase == "cold"), None)
        warm = next((record for record in pair if record.phase == "warm"), None)
        if cold is None or warm is None:
            errors.append(f"{pair_id}: cold/warm pair incomplete")
            continue
        if cold.audit_retrieval_id is None or warm.audit_retrieval_id is None:
            errors.append(f"{pair_id}: missing retrieval audit id")
        elif cold.audit_retrieval_id == warm.audit_retrieval_id:
            errors.append(f"{pair_id}: retrieval audit id was reused")
        if cold.audit_user_id != expected_user_id or warm.audit_user_id != expected_user_id:
            errors.append(f"{pair_id}: authenticated audit user id was not preserved")
    return errors


def safe_cache_status(
    session: requests.Session,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    response = session.get(
        base_url.rstrip("/") + "/api/v1/admin/cache/status",
        timeout=timeout,
    )
    if response.status_code == 403:
        return {"available_to_account": False}
    response.raise_for_status()
    payload = response.json()
    return {
        "available_to_account": True,
        "enabled": bool(payload.get("enabled")),
        "connected": bool(payload.get("connected")),
        "namespace": payload.get("namespace"),
        "version": payload.get("version"),
        "knowledge_generation": payload.get("knowledge_generation"),
    }


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if key.casefold() not in SENSITIVE_FIELDS
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def build_report(
    args: argparse.Namespace,
    records: list[RunRecord],
    *,
    user_id: int,
    role: str,
    cache_status: dict[str, Any] | None,
    audit_errors: list[str],
) -> dict[str, Any]:
    return sanitize(
        {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "benchmark_kind": "paired_cold_warm",
                "percentile_method": "nearest-rank",
            },
            "configuration": {
                "base_url": args.base_url,
                "email": args.email,
                "role": role,
                "authenticated_user_id": user_id,
                "route": args.route,
                "repetitions": args.repetitions,
                "warmups": args.warmups,
                "limit": args.limit,
                "timeout_seconds": args.timeout,
                "fixtures_file": str(args.fixtures),
                "performance_log_observation": bool(args.performance_log),
                "expect_cache_unavailable": args.expect_cache_unavailable,
            },
            "cache_status": cache_status,
            "runs": [asdict(record) for record in records],
            "aggregates": aggregate_records(records),
            "audit_validation": {
                "passed": not audit_errors,
                "errors": audit_errors,
            },
            "quality_summary": {
                "passed": sum(record.quality_pass is True for record in records),
                "failed": sum(record.quality_pass is False for record in records),
                "note": "Expected-term checks are smoke checks, not proof of model correctness.",
            },
        }
    )


def print_report(report: dict[str, Any]) -> None:
    print("Performance benchmark")
    print(
        "Client durations are end-to-end; server stage timings appear only when "
        "--performance-log is supplied."
    )
    for aggregate in report["aggregates"]:
        mean = aggregate["mean_ms"]
        rendered_mean = "n/a" if mean is None else f"{mean / 1000:.3f} s"
        print(
            f"{aggregate['route']} / {aggregate['fixture']} / {aggregate['phase']}: "
            f"mean {rendered_mean}, ok {aggregate['successful_requests']}, "
            f"failed {aggregate['failed_requests']}, "
            f"hits {aggregate['cache_hit_count']}, misses {aggregate['cache_miss_count']}"
        )
    audit = report["audit_validation"]
    print(f"Audit preservation: {'PASS' if audit['passed'] else 'FAIL'}")
    quality = report["quality_summary"]
    print(f"Expected-term smoke checks: {quality['passed']} passed, {quality['failed']} failed")


def run_benchmark(
    args: argparse.Namespace,
    *,
    session: requests.Session | None = None,
    password: str | None = None,
) -> tuple[dict[str, Any], int]:
    client = session or requests.Session()
    owns_session = session is None
    token: str | None = None
    secret = password if password is not None else os.getenv("BENCHMARK_PASSWORD")
    if not secret:
        raise ValueError("BENCHMARK_PASSWORD is required")
    log_offset = 0
    if args.performance_log:
        log_offset = args.performance_log.stat().st_size
    try:
        token, user_id, role = authenticate(
            client,
            args.base_url,
            args.email,
            secret,
            args.timeout,
        )
        client.headers.update({"Authorization": f"Bearer {token}"})
        cache_status = (
            safe_cache_status(client, args.base_url, args.timeout)
            if args.check_cache_status
            else None
        )
        fixtures = load_fixtures(args.fixtures)
        selected_routes = list(ROUTE_PATHS) if args.route == "all" else [args.route]
        records: list[RunRecord] = []
        for route in selected_routes:
            for fixture in fixtures:
                if route not in fixture["routes"]:
                    continue
                for repetition in range(1, args.repetitions + 1):
                    pair_id = uuid.uuid4().hex
                    cold_query = f"{fixture['query']} [benchmark {pair_id}]"
                    records.append(
                        perform_request(
                            client,
                            base_url=args.base_url,
                            route=route,
                            fixture=fixture,
                            query=cold_query,
                            phase="cold",
                            repetition=repetition,
                            pair_id=pair_id,
                            limit=args.limit,
                            timeout=args.timeout,
                        )
                    )
                    for _ in range(args.warmups):
                        perform_request(
                            client,
                            base_url=args.base_url,
                            route=route,
                            fixture=fixture,
                            query=cold_query,
                            phase="warmup",
                            repetition=repetition,
                            pair_id=pair_id,
                            limit=args.limit,
                            timeout=args.timeout,
                        )
                    records.append(
                        perform_request(
                            client,
                            base_url=args.base_url,
                            route=route,
                            fixture=fixture,
                            query=cold_query,
                            phase="warm",
                            repetition=repetition,
                            pair_id=pair_id,
                            limit=args.limit,
                            timeout=args.timeout,
                        )
                    )
        if args.performance_log:
            attach_log_observations(
                records,
                read_log_events(args.performance_log, log_offset),
                args.warmups,
            )
        audit_errors = validate_audit_pairs(records, user_id)
        report = build_report(
            args,
            records,
            user_id=user_id,
            role=role,
            cache_status=cache_status,
            audit_errors=audit_errors,
        )
        failed = any(not record.success for record in records) or bool(audit_errors)
        quality_failed = any(record.quality_pass is False for record in records)
        if args.expect_cache_unavailable:
            status_observed = bool(
                cache_status
                and cache_status.get("available_to_account")
                and (
                    not cache_status.get("enabled")
                    or not cache_status.get("connected")
                )
            )
            logs_observed = any(record.cache_state == "unavailable" for record in records)
            if not (status_observed or logs_observed):
                failed = True
                report["cache_unavailable_validation"] = {
                    "passed": False,
                    "error": "cache unavailability was not observed",
                }
            else:
                report["cache_unavailable_validation"] = {"passed": True}
        return report, 1 if failed or quality_failed else 0
    finally:
        client.headers.pop("Authorization", None)
        token = None
        secret = None
        if owns_session:
            client.close()


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
