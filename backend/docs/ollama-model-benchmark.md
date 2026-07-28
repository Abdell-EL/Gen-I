# Phase 4C.2 controlled Ollama benchmark runbook

This benchmark compares generation configurations without changing application
defaults. It is an explicit operator command: it never starts, stops, restarts, pulls,
or unloads a model and never changes Docker Compose or `.env`.

The script authenticates to the real API, retrieves the top five ranked chunks once
per fixture through `/api/v1/search`, verifies the returned audit user, and reuses that
same evidence for every model experiment. It then calls Ollama's generate endpoint
directly. This isolates model, context, and output-length effects without changing the
production `/chat` schema, prompt, authentication, retrieval ranking, or audit logic.

## Current production baseline

- Model: `llama3.2:3b`
- Fast model: `llama3.2:1b`, disabled by default
- Context window: 4,096 tokens
- Prediction limit: 350 tokens
- Temperature: 0.1
- Retrieved chunks: top five, in ranking order
- Maximum assembled context: 12,000 characters
- Keep-alive: `10m`

Phase 4C.2 does not change these values.

## Hardware capability audit

Run these read-only commands on the actual benchmark host before publishing results:

```bash
ollama ps
free -h
grep -E 'MemTotal|MemAvailable' /proc/meminfo
```

`ollama ps` reports the loaded model, size, processor allocation, and expiry. Record
exactly what its `PROCESSOR` column says; do not infer GPU use from model speed.

Check NVIDIA hardware only when the command is installed:

```bash
command -v nvidia-smi
nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
```

An unavailable `nvidia-smi`, an empty device list, or CPU shown by `ollama ps` is not
evidence of GPU support. Other GPU vendors require their corresponding vendor tool.

Inspect only Docker GPU device requests, without printing container environment
variables:

```bash
docker inspect lab_ollama \
  --format '{{json .HostConfig.DeviceRequests}}'
```

The current Compose file contains no explicit Ollama GPU device reservation. This is
only a configuration observation; actual processor use must still be confirmed with
`ollama ps` on the benchmark host.

Also record host CPU and container resource limits:

```bash
lscpu
docker inspect lab_ollama \
  --format 'NanoCPUs={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}}'
```

None of these commands changes service state.

## Credentials and prerequisites

- Use a non-production benchmark environment.
- Ensure `llama3.2:3b` is available before baseline testing.
- Install `llama3.2:1b` manually before selecting a fast profile.
- Use an active admin or agent account that may create retrieval audits.
- Run from `backend/` with its Python environment active.

Read the API password without placing it in command arguments:

```bash
read -rsp "Benchmark password: " BENCHMARK_PASSWORD
export BENCHMARK_PASSWORD
export BENCHMARK_OLLAMA_URL=http://127.0.0.1:11434/api/generate
```

The Ollama URL is used but omitted from JSON and console reports. The password and
access token are neither printed nor persisted.

## Explicit model profiles

Profiles live in `scripts/fixtures/ollama_profiles.json`:

- `baseline_3b`: `llama3.2:3b`, 350 prediction tokens.
- `concise_3b`: `llama3.2:3b`, 160 prediction tokens, with a benchmark-only concise
  instruction.
- `fast_1b`: `llama3.2:1b`, 350 prediction tokens.
- `fast_1b_concise`: optional `llama3.2:1b`, 160 prediction tokens and concise
  instruction.

Only `baseline_3b` is selected by default. A 1B profile must appear explicitly in
`--profiles`; no automatic routing or fallback selects it.

Baseline smoke run:

```bash
python3 scripts/benchmark_ollama_profiles.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --profiles baseline_3b \
  --repetitions 3 \
  --json-output ollama-baseline.json
```

Controlled 3B versus 1B comparison:

```bash
python3 scripts/benchmark_ollama_profiles.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --profiles baseline_3b,concise_3b,fast_1b,fast_1b_concise \
  --repetitions 5 \
  --warmups 1 \
  --json-output ollama-model-comparison.json
```

## Context and generation experiments

The following produces a full explicit cross-product. It can be large: four
prediction limits × two chunk counts × two budgets = 16 configurations per profile
and fixture.

```bash
python3 scripts/benchmark_ollama_profiles.py \
  --base-url http://127.0.0.1:8000 \
  --email benchmark@example.invalid \
  --profiles baseline_3b,fast_1b \
  --prediction-limits 350,192,128,96 \
  --chunk-counts 5,3 \
  --context-budgets 12000,6000 \
  --repetitions 3 \
  --warmups 1 \
  --json-output ollama-context-generation-matrix.json
```

Rank order is never changed. Each run reports selected, included, and omitted source
IDs. A smaller character budget may omit or truncate lower-ranked evidence. Top three
is an experiment, not a new default; adopt it only after fixture and human review show
acceptable quality.

The concise instruction is appended only to the generated benchmark prompt. It does
not edit the production prompt builder.

## Measurements and interpretation

Each run records:

- Explicit profile, model, context window, prediction limit, chunk count, and budget
- Selected, included, and omitted source IDs
- Assembled context characters
- Client-observed generation duration
- Ollama total, prompt-evaluation, and generation durations when returned
- Native prompt/completion token counts when returned
- Approximate output token count when native counts are unavailable
- Approximate generation tokens/second when Ollama returns `eval_duration`
- Quality smoke checks, truncation warning, completeness category, and answer text

Client time includes HTTP overhead. Ollama's nanosecond duration counters are reported
separately. Approximate tokens/second is `eval_count / eval_duration`; it must not be
substituted for client end-to-end throughput.

Aggregates are separated by profile, exact experiment, and fixture. P50 and P95 use
nearest-rank: sort samples and select rank `ceil(percentile / 100 × count)`. Never
combine 1B and 3B latency into a single aggregate.

## Quality rubric

Each fixture declares:

- Expected business code or term
- Whether retrieval sources are required
- Known unsupported codes that must not appear
- Minimum direct-answer length

Automated checks classify answers:

- `pass`: expected terms and sources are present, no listed unsupported code appears,
  the response directly addresses the question, and no truncation is detected.
- `partial`: the response is direct and most checks pass, but at least one concern
  remains.
- `fail`: generation failed or essential smoke checks failed.

Source preservation refers to the separately reported ranked source IDs, matching the
existing API's answer-plus-sources behavior; it does not pretend that every answer has
inline citations. Truncation uses Ollama's completion reason and a conservative
prediction-limit/terminal-punctuation heuristic.

These are smoke tests only. JSON and console output include every redacted answer in a
clearly marked human-review section. Review factual support, operational usefulness,
missing caveats, incorrect codes, and whether shorter answers remain complete. Do not
select the shortest or fastest profile solely on latency.

## Temporary application profile selection

The benchmark itself does not require changing or restarting the API. If an operator
later wants to validate a chosen profile through the real `/chat` endpoint, use a
separate non-production process with explicit environment variables.

Baseline local process:

```bash
OLLAMA_MODEL=llama3.2:3b \
OLLAMA_USE_FAST_MODEL=false \
OLLAMA_NUM_CTX=4096 \
OLLAMA_NUM_PREDICT=350 \
OLLAMA_MAX_CONTEXT_CHARS=12000 \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Explicit fast local process:

```bash
OLLAMA_FAST_MODEL=llama3.2:1b \
OLLAMA_USE_FAST_MODEL=true \
OLLAMA_NUM_CTX=4096 \
OLLAMA_NUM_PREDICT=160 \
OLLAMA_MAX_CONTEXT_CHARS=12000 \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Stopping that temporary foreground process is the rollback. For a managed
non-production deployment, set the same non-secret variables through its deployment
configuration and recreate only the API service manually. Roll back explicitly to:

```text
OLLAMA_MODEL=llama3.2:3b
OLLAMA_FAST_MODEL=llama3.2:1b
OLLAMA_USE_FAST_MODEL=false
OLLAMA_NUM_CTX=4096
OLLAMA_NUM_PREDICT=350
OLLAMA_TEMPERATURE=0.1
OLLAMA_KEEP_ALIVE=10m
OLLAMA_MAX_CONTEXT_CHARS=12000
```

Apply the rollback using the deployment's normal API-service restart procedure, then
verify the safe admin performance/cache status and a test chat. Never edit secret
values, and never leave `OLLAMA_USE_FAST_MODEL=true` after the experiment.

Finally:

```bash
unset BENCHMARK_PASSWORD
unset BENCHMARK_OLLAMA_URL
```

No command in the benchmark script restarts containers, pulls models, or changes
production data beyond the normal authenticated retrieval audit created for each
fixture.
