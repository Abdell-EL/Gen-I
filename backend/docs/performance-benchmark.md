# Phase 4C.1 performance benchmark runbook

This workflow is opt-in. The script does not start, stop, restart, unload, flush, or
otherwise manage Docker, Redis, Ollama, PostgreSQL, or Milvus. It runs only when an
operator explicitly invokes it.

## Prerequisites

- Run the API and its normal dependencies in a non-production benchmark environment.
- Use an active admin or agent account. An admin is needed for `--check-cache-status`.
- Ensure the chosen account may create normal retrieval audit records.
- Run commands from `backend/` with its Python environment active.
- Prefer an isolated server process and log file when using `--performance-log`.

Set the password without putting it in shell history or process arguments:

```bash
read -rsp "Benchmark password: " BENCHMARK_PASSWORD
export BENCHMARK_PASSWORD
```

The script never accepts `--password`, prints a token, or writes credentials to JSON.

## Commands

Search only:

```bash
python scripts/benchmark_performance.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --route search \
  --repetitions 10 \
  --warmups 1 \
  --check-cache-status \
  --json-output benchmark-search.json
```

Chat only:

```bash
python scripts/benchmark_performance.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --route chat \
  --repetitions 5 \
  --warmups 1 \
  --json-output benchmark-chat.json
```

All routes with optional internal timing/cache observations from a dedicated server log:

```bash
python scripts/benchmark_performance.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --route all \
  --performance-log /tmp/lab-ia-benchmark-server.log
```

Unset the credential afterward:

```bash
unset BENCHMARK_PASSWORD
```

## Cold and warm definitions

Each repetition is a pair. The cold request appends an opaque benchmark discriminator
to a fixture query, producing a deliberately uncached query without deleting or
flushing any Redis key. Warm-up requests and the recorded warm request repeat that
exact query and retrieval settings. The cold and warm requests therefore can share
retrieval candidates while still creating separate, user-attributed audit rows.

The discriminator slightly changes the text sent to retrieval. For presentation-grade
comparisons, use an isolated benchmark deployment with a unique `CACHE_NAMESPACE` or
`CACHE_VERSION`; then the fixture text can be tested independently without affecting
production cache contents. Never flush a shared production namespace.

“Cold chat” in the default report means cold retrieval, not a guaranteed unloaded
Ollama model. A true Ollama cold-start measurement requires an operator to prepare an
isolated environment manually and confirm that disruption is acceptable. The script
does not stop a container or unload a model. A warm-up chat loads the model; subsequent
recorded chats are warm-model candidates. Because complete answers are not cached,
every warm chat still performs generation. Only embedding/retrieval work may be reused.

## Cache and timing interpretation

Console and JSON durations are client-observed end-to-end timings measured with
`time.perf_counter()`. They include transport and cannot be presented as precise
internal Ollama latency.

Per-request retrieval and embedding hit/miss status is not exposed in normal API
responses. When `--performance-log` points to a dedicated structured server log, the
script reads only newly appended performance events and attaches the existing safe
stage timings and statuses. Run no unrelated traffic through that process while
collecting logs because matching is chronological. Without the log, cache state is
reported as `not_observed`, never guessed.

`--check-cache-status` calls the existing admin-only safe status endpoint. It reports
enabled/connected state but not raw keys, hosts, URLs, credentials, query hashes, or
cached values. Agent accounts receive a harmless “not available to account” result.

To test fail-open behavior, arrange Redis unavailability manually in an isolated
environment, then run:

```bash
python scripts/benchmark_performance.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark-admin@example.invalid \
  --route search \
  --check-cache-status \
  --expect-cache-unavailable
```

The flag never stops Redis. It succeeds only when requests succeed and unavailability
is observed through admin status or structured logs.

## Audit and quality checks

For every cold/warm pair the benchmark requires different retrieval audit IDs and the
same authenticated user ID returned by signin. It never deletes audit records. This
demonstrates that candidate reuse does not reuse another user’s audit ownership.

Expected terms are deterministic smoke checks over answers and returned source/result
metadata. They can catch obvious regressions but do not prove model correctness,
factuality, or answer quality.

## Statistics and sample sizes

Statistics are grouped by route, fixture, and cold/warm phase, so search and chat
latencies are never combined. Minimum, maximum, mean, median, P50, and P95 use only
successful requests. P50 and P95 use the nearest-rank method: sort observations and
select rank `ceil(percentile / 100 * count)`.

Five repetitions are suitable for a smoke run. Use at least 20 per fixture for a
presentation and 30–100 under controlled, steady load for engineering decisions.
Small samples make P95 unstable. Record CPU/GPU allocation, host load, model, cache
configuration, and concurrent traffic alongside any published benchmark.
