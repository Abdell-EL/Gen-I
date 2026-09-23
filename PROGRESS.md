# Progress

A running log of changes made to this repository, most recent first.

## 2026-09-23 — First real quality verification pass, and an honest gap found

**Files:** `backend/app/services/ollama_service.py`,
`backend/scripts/benchmark_performance.py`,
`backend/scripts/fixtures/performance_queries.json`,
`backend/tests/test_benchmark_performance.py`

Ran the existing (but never actually exercised) quality-benchmark
infrastructure — `scripts/benchmark_performance.py` +
`scripts/fixtures/performance_queries.json` — against the live pipeline,
plus 3 additional real questions already manually validated. First pass
reported 7/7, but that was misleading: `quality_check()` tested expected
terms against the answer **and the raw retrieved source chunks combined**,
so a term could "pass" purely by sitting in a source the model never
actually used. Checked against the generated answer alone instead: **6/7**.

The one real failure ("Comment clôturer un OT PMR FTH..." — a pasted,
messy operator ticket comment, not a clean question) turned out to be a
generation problem, not a retrieval one: the single correct rule was
ranked **#1** among the 5 retrieved chunks, but the model still concluded
no rule applied. The existing closure-code heuristics
(`_is_closure_code_question`, `_is_direct_closure_rule`) don't cover this
phrasing or this rule's vocabulary ("code erreur" vs. the phrases they
match on), so they never activated.

Added a general instruction to `build_grounded_prompt()`: examine each
source individually, in order, before concluding information is absent.
Verified against all 7 fixtures — 6 continue to pass, and the 7th improved
from an unhelpful blanket denial to correctly citing the right source with
the right general action, but still doesn't reliably restate the exact
numeric code. A second, more specific instruction (quote any code number
verbatim) was tried and reverted — it caused the model to pick the wrong
of two similarly-worded competing rules on the same question, trading one
failure mode for another.

**Honest state:** this one case is left as a known, tracked limitation —
now a permanent fixture (`ot_pmr_fth_commentaire_libre`) rather than an
undocumented gap — likely a real capability ceiling of the small 3B model
on messy free-text input, not something more prompt-tuning reliably fixes.

Also fixed `quality_check()` itself so future benchmark runs on the chat
route check the answer alone, and expanded the fixture file from 4 to 7
real, validated questions as an actual regression suite. Full test suite
(269 tests) passes. Image rebuilt and redeployed.

_Commits: `0f3e955`, `c4fe776`_

## 2026-09-23 — Cache the actual generated answer, not just retrieval

**Files:** `backend/app/config.py`, `backend/app/services/ollama_service.py`,
`backend/tests/test_chat.py`, `backend/tests/test_phase4b_performance.py`

Retrieval was already cached and fast; the LLM-generated answer itself was
not. A literal repeat of a question always called Ollama fresh, unless it
happened to still occupy one of Ollama's 4 prompt-cache slots — which get
evicted after a handful of other questions, so most real repeats still paid
the full ~30-45s generation cost.

Added a Redis-backed answer cache, keyed on the exact rendered prompt (the
question, retrieved context, and conversation history are all already baked
into that string, so anything that changes any of them naturally produces a
different key — no separate invalidation bookkeeping needed). Configurable
via `CACHE_ANSWER_TTL_SECONDS` (default 6h, longer-lived than Ollama's own
volatile slots). Wired into both the non-streaming and streaming generation
paths — a streaming cache hit replays the cached answer as a single
synthetic token event + done event instead of calling Ollama. Fails open
like every other cache here: a cache outage never breaks an answer, it just
stops being instant.

Verified end-to-end against the live system: a repeated question dropped
from ~38,957ms to 0ms, identical answer. Full backend test suite (268 tests,
3 new ones covering the cache-hit/miss/different-question behavior on both
paths) passes. Image rebuilt and redeployed.

_Commit: `3f622f5`_

## 2026-09-22 — Ollama: keep more than one prompt's cache warm

**File:** `docker-compose.yml`

With retrieval now fast, the remaining bottleneck for a genuinely new
question is Ollama's own generation time (~30-55s on this CPU-only VM for
a fresh prompt — 2 physical cores, no GPU). Investigated why *some*
questions came back fast (~5s) and others didn't: Ollama's llama.cpp
backend was running with only one prompt-cache "slot" (`n_slots = 1`,
confirmed in its startup logs), so it could only keep the single most
recently processed prompt warm. Asking question A, then question B, then
A again evicted A's cached state when B ran — A had to be reprocessed
from scratch even though it had just been asked minutes earlier.

Set `OLLAMA_NUM_PARALLEL=4` on the `ollama` service. Memory cost is
trivial (~450MB per slot against 31GB free on this box) and there's no
compute cost from added slots when requests arrive sequentially, as they
do here — this isn't about concurrency, purely about cache retention.

Verified with a real A → B → A sequence, real questions, real retrieved
context:

| | Time |
|---|---|
| A (1st, cold) | 34.8 s |
| B (cold, different question) | 55.3 s |
| A (2nd, after B in between) | **5.8 s** |

Before this change, that third call would have been cold again (~35s).
Also benchmarked whether switching the default model to the smaller
`llama3.2:1b` was a better lever: it's 1.3-3x faster, and got every
tested fact right, but showed occasional citation/grounding issues
(a mismatched source once, a self-contradicting sentence once) that
matter for a system whose value is verifiable, sourced answers — left
`llama3.2:3b` as the default given that tradeoff.

_Commit: `c9db58c`_

## 2026-09-22 — Retrieval pipeline: stop re-embedding candidates Milvus already has

**File:** `backend/app/services/retrieval_service.py`

Benchmarking the previous fix on real production data surfaced a much larger
problem in the same function: `_lexical_current_version_candidates()` was
calling `model.encode()` on up to 50 lexical-fallback candidate texts on
every cache-miss query — even though every one of those chunks was already
embedded once at ingestion time and is stored in Milvus. Measured on this
server: that single step took **~46 seconds** out of a **~51-second**
`search_chunks()` call, over 99% of total retrieval latency for any
question that wasn't already cached.

Fixed by fetching those vectors directly from Milvus by id
(`collection.query(expr="id in [...]", output_fields=["embedding"])` — the
same pattern `milvus_writer_service.py` already used to check existing
ids), falling back to `model.encode()` only for the rare candidate Milvus
doesn't have. Verified the id scheme lines up by testing real chunk ids
against the live collection before writing the fix (5/5, then 50/50,
matched).

Re-benchmarked end-to-end after the fix, same real data, same running
system:

| | Before | After |
|---|---|---|
| Cache-miss query (warm model) | ~29,600 - 35,000 ms | ~560 - 569 ms |
| Candidate re-embedding step | ~46,193 ms | ~2 ms (Milvus lookup) |

Roughly a **50-60x speedup**, identical results and ranking. Full backend
suite (265 tests) passes; `tests/test_phase4b_performance.py`'s
`FakeCollection` gained a `query()` stub so tests keep exercising the
encode-fallback path they were already written around. Rebuilt the `api`
Docker image and redeployed; confirmed the fix is present in the rebuilt
image and re-benchmarked against it directly.

_Commit: `b93e41f`_

## 2026-09-21 — Retrieval pipeline: remove duplicate query embedding

**File:** `backend/app/services/retrieval_service.py`

`_lexical_current_version_candidates()` (the Postgres lexical fallback used
inside `search_chunks()`) was re-encoding the user's query from scratch with
a raw `model.encode()` call, even though `search_chunks()` had already
computed and cached that exact same embedding a few lines earlier via
`embed_query()`. Same model, same deterministic input text, same output
vector — just wasted compute on every cache-miss retrieval.

Fixed by threading the already-computed `query_vector` into
`_lexical_current_version_candidates()` as a parameter instead of
re-deriving it. Removed `_embedding_vector()`, which had no other caller
once the redundant call was gone.

No behavior change — same candidates, same ranking, one fewer embedding
inference per query. Verified against the full backend suite
(`python -m unittest discover -s tests`, 265 tests, all passing) and the
hybrid-retrieval tests specifically.

_Commit: `e1510c2`_

## 2026-09-18 — Fix CORS blocking login on the deployed frontend

**File:** `backend/app/main.py`

The backend's CORS `allow_origins` only listed the Vite dev-server origins
(`http://127.0.0.1:5173`, `http://localhost:5173`). Anyone using the app
through its actual deployed URL (`http://localhost`, nginx on port 80) had
every authenticated request silently blocked by the browser's CORS check —
surfacing to the user as a generic "email ou mot de passe incorrect" error,
regardless of whether their credentials were correct.

Added `http://localhost` and `http://127.0.0.1` to `allow_origins`. Rebuilt
and redeployed the `api` Docker image for the change to take effect.

_Commit: `f45f283`_

## 2026-09-17 — Replace the text-only brand mark with the official logo

**Files:** `backend/frontend/src/components/layout/BrandLockup.tsx`,
`backend/frontend/src/styles/global.css`,
`backend/frontend/src/assets/genius-services-logo.png`

The shared `BrandLockup` component (used in the public nav, sign-in panel,
agent sidebar, admin sidebar, dashboard topbar, and 404 page) rendered
"Genius Services" as plain text. Replaced it with an `<img>` of the official
logo, sized responsively (`object-fit: contain`, height-constrained) and
wired into the existing sidebar collapse/hover-expand animations so it
behaves exactly like the text it replaced at every breakpoint.

The logo asset itself had been saved with a `.svg` extension despite being
real PNG data — renamed to `.png` to avoid a MIME-type mismatch that would
have broken rendering in production.

Left every other occurrence of "Genius Services" (page copy, accessibility
labels, the backend API title) untouched — only the visual brand mark was
replaced.

Verified with `npm run lint`, `npm test` (48 tests), and `npm run build`,
plus a manual pass through the deployed app.

_Commit: `9e4c5ca`_
