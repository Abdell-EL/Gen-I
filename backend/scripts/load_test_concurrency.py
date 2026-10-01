#!/usr/bin/env python3
"""Concurrency load test for the chat pipeline.

Purpose: answer one specific question with real numbers instead of an
estimate — "if N agents ask a real question within the same few seconds,
what's the actual latency distribution and failure rate?" This is the
validation step that should run against a candidate GPU VM / Azure AI
Foundry deployment BEFORE committing budget to it, not something to run
against shared production (it deliberately generates real, uncached load).

Usage:
    python scripts/load_test_concurrency.py \\
        --base-url http://<candidate-host> \\
        --email agent-test-1@example.com --password '...' \\
        --concurrency 100 --route chat

Requires an existing agent/admin account on the target deployment.

IMPORTANT — semantic caching will silently make results look better than
reality if you don't account for it. The app has a semantic answer cache
(paraphrase-matching, not just exact text) that this script's per-request
"(test <marker>-<n>)" suffix does NOT defeat — appending a short marker
barely moves a whole question's embedding, so once a question from the pool
has been asked (in this run or any earlier one), later "unique" variants of
it will still cosine-match and return in milliseconds without generating
anything. Verified directly: reusing the well-worn default fixture
questions produced a ~1 second false result; the same test with genuinely
novel questions (never asked before) correctly took 120s+ under load.

For a trustworthy capacity number, do ONE of:
  1. Run the target deployment with CACHE_ENABLED=false for the duration of
     the test (cleanest — disables the retrieval, embedding, and answer
     caches together, since they share the same settings flag), or
  2. Supply a --fixtures file of genuinely novel questions nobody has ever
     asked this deployment before, and only run it once per deployment.
Do not trust a suspiciously fast result without one of the above.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_FIXTURES = Path(__file__).with_name("fixtures") / "performance_queries.json"

FALLBACK_QUESTIONS = [
    "Quel code situation utiliser pour une demande d'autorisation voisinage ?",
    "Quelle procédure suivre pour un problème de regard ?",
    "Explique les règles de choix des codes de clôture FTTH.",
    "Comment traiter un ticket lorsque le client refuse le rendez-vous technicien ?",
    "Que faire si l'installation est reportée par le client ?",
    "Quel commentaire libre utiliser pour un OT PMR FTH ?",
    "Quel est le délai standard pour une intervention technicien ?",
]


@dataclass
class RequestResult:
    virtual_user: int
    question: str
    http_status: int | None
    duration_ms: float
    time_to_first_token_ms: float | None
    success: bool
    error: str | None
    answer_chars: int | None
    confidence: str | None


def load_question_pool(fixtures_path: Path) -> list[str]:
    if fixtures_path.exists():
        try:
            data = json.loads(fixtures_path.read_text(encoding="utf-8"))
            questions = [item["query"] for item in data if item.get("query")]
            if questions:
                return questions
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return FALLBACK_QUESTIONS


def question_for(pool: list[str], index: int, run_marker: str) -> str:
    base = pool[index % len(pool)]
    # A harmless trailing marker keeps every request's exact text unique
    # (defeats the exact-match answer cache) without touching the meaning
    # the retrieval step reads.
    return f"{base} (test {run_marker}-{index})"


async def sign_in(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> str:
    response = await client.post(
        f"{base_url}/api/v1/auth/signin",
        json={"email": email, "password": password},
        timeout=30.0,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise SystemExit("Sign-in response did not contain an access_token.")
    return token


async def run_chat_request(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    virtual_user: int,
    question: str,
    timeout: float,
    start_gate: asyncio.Event,
) -> RequestResult:
    await start_gate.wait()
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url}/api/v1/chat",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        duration_ms = (time.perf_counter() - started) * 1000
        body = response.json() if response.status_code == 200 else {}
        return RequestResult(
            virtual_user=virtual_user,
            question=question,
            http_status=response.status_code,
            duration_ms=duration_ms,
            time_to_first_token_ms=None,
            success=response.status_code == 200,
            error=None if response.status_code == 200 else response.text[:300],
            answer_chars=len(body.get("answer", "")) if body else None,
            confidence=body.get("confidence") if body else None,
        )
    except Exception as error:  # noqa: BLE001 - report every failure mode in results
        return RequestResult(
            virtual_user=virtual_user,
            question=question,
            http_status=None,
            duration_ms=(time.perf_counter() - started) * 1000,
            time_to_first_token_ms=None,
            success=False,
            error=f"{type(error).__name__}: {error}",
            answer_chars=None,
            confidence=None,
        )


async def run_chat_stream_request(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    virtual_user: int,
    question: str,
    timeout: float,
    start_gate: asyncio.Event,
) -> RequestResult:
    await start_gate.wait()
    started = time.perf_counter()
    first_token_at: float | None = None
    answer_chars = 0
    confidence: str | None = None
    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/v1/chat/stream",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        ) as response:
            if response.status_code != 200:
                text = await response.aread()
                return RequestResult(
                    virtual_user=virtual_user,
                    question=question,
                    http_status=response.status_code,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    time_to_first_token_ms=None,
                    success=False,
                    error=text[:300].decode("utf-8", "replace"),
                    answer_chars=None,
                    confidence=None,
                )
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("type") == "metadata":
                    confidence = event.get("confidence")
                elif event.get("type") == "token":
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    answer_chars += len(event.get("text", ""))
        duration_ms = (time.perf_counter() - started) * 1000
        ttft_ms = (first_token_at - started) * 1000 if first_token_at else None
        return RequestResult(
            virtual_user=virtual_user,
            question=question,
            http_status=200,
            duration_ms=duration_ms,
            time_to_first_token_ms=ttft_ms,
            success=True,
            error=None,
            answer_chars=answer_chars,
            confidence=confidence,
        )
    except Exception as error:  # noqa: BLE001
        return RequestResult(
            virtual_user=virtual_user,
            question=question,
            http_status=None,
            duration_ms=(time.perf_counter() - started) * 1000,
            time_to_first_token_ms=None,
            success=False,
            error=f"{type(error).__name__}: {error}",
            answer_chars=None,
            confidence=None,
        )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarize(results: list[RequestResult], wall_clock_s: float) -> None:
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    durations = [r.duration_ms for r in successes]

    print("\n=== Load test summary ===")
    print(f"Concurrent requests fired : {len(results)}")
    print(f"Succeeded                 : {len(successes)}")
    print(f"Failed                    : {len(failures)}")
    print(f"Wall clock for the batch  : {wall_clock_s:.1f} s")
    if successes:
        print(f"Effective throughput      : {len(successes) / wall_clock_s:.2f} answers/sec")
        print("\nLatency (successful requests only):")
        print(f"  min    : {min(durations):.0f} ms")
        print(f"  p50    : {percentile(durations, 50):.0f} ms")
        print(f"  p90    : {percentile(durations, 90):.0f} ms")
        print(f"  p95    : {percentile(durations, 95):.0f} ms")
        print(f"  p99    : {percentile(durations, 99):.0f} ms")
        print(f"  max    : {max(durations):.0f} ms")
        print(f"  mean   : {statistics.mean(durations):.0f} ms")
        ttft_values = [r.time_to_first_token_ms for r in successes if r.time_to_first_token_ms is not None]
        if ttft_values:
            print("\nTime to first token (streaming only):")
            print(f"  p50    : {percentile(ttft_values, 50):.0f} ms")
            print(f"  p95    : {percentile(ttft_values, 95):.0f} ms")
    if failures:
        print("\nFailure samples (first 5):")
        for failure in failures[:5]:
            print(f"  user {failure.virtual_user}: status={failure.http_status} error={failure.error}")
    print("=========================\n")


async def main_async(args: argparse.Namespace) -> int:
    pool = load_question_pool(args.fixtures)
    run_marker = uuid.uuid4().hex[:8]

    async with httpx.AsyncClient() as auth_client:
        token = await sign_in(auth_client, args.base_url, args.email, args.password)

    runner = run_chat_stream_request if args.route == "chat-stream" else run_chat_request

    start_gate = asyncio.Event()
    limits = httpx.Limits(max_connections=args.concurrency + 5, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [
            asyncio.create_task(
                runner(
                    client,
                    args.base_url,
                    token,
                    virtual_user,
                    question_for(pool, virtual_user, run_marker),
                    args.timeout,
                    start_gate,
                )
            )
            for virtual_user in range(args.concurrency)
        ]

        # All tasks are now created and waiting on start_gate; releasing it
        # fires every request as close to simultaneously as asyncio allows —
        # this is what simulates "100 people ask a question at the same time"
        # rather than 100 requests trickling out one after another.
        started = time.perf_counter()
        start_gate.set()
        results = await asyncio.gather(*tasks)
        wall_clock_s = time.perf_counter() - started

    summarize(results, wall_clock_s)

    if args.json_output:
        args.json_output.write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Raw per-request results written to {args.json_output}")

    return 0 if all(r.success for r in results) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True, help="Existing agent/admin account on the target deployment.")
    parser.add_argument("--password", required=True)
    parser.add_argument("--concurrency", type=int, default=100, help="Number of simultaneous virtual users.")
    parser.add_argument("--route", choices=["chat", "chat-stream"], default="chat")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout in seconds.")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
