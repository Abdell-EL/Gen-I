# Progress

A running log of changes made to this repository, most recent first.

## 2026-10-08 — Frontend was calling the API at a hardcoded dev-only address

**Files:** `backend/frontend/.env.production`, `.gitignore`

User reported the app showing a stuck blank page, then after that resolved,
sign-in failing with a generic "wrong email/password" even though the
credentials were correct. Checked the live server first (healthy, fast,
zero connection-pool pressure) and the live logs (the sign-in request never
arrived at all) before looking at the frontend — confirmed this wasn't a
backend problem before touching anything there.

Root cause: the production build had never had `VITE_API_BASE_URL` set, so
it fell back to its dev-only default, `http://127.0.0.1:8000`, baked into
the deployed bundle. nginx already proxies `/api/` to the backend on the
same port 80 the page itself loads from — the frontend just wasn't using
that path, so every API call needed its own separate port-8000 tunnel to
the user's browser, on top of port 80 for the page. Any gap in either
tunnel broke a different half of the app in a confusing way (page loads,
nothing else works) — explaining both symptoms as one underlying cause.

Added `backend/frontend/.env.production` setting `VITE_API_BASE_URL=/api/v1`
(a relative path), so a production build always calls the API through the
same origin/port the page itself was served from — no second tunnel needed.
Local dev (`vite dev`, separate frontend/backend ports) is unaffected: that
mode doesn't read `.env.production`, so it keeps using the existing
absolute-URL fallback.

`.gitignore` had a blanket `.env.*` rule that would have silently excluded
this file (it's not a secret — just a public build-time routing value) —
added an explicit exception, the same pattern already used for
`.env.example`, so this fix can't quietly disappear on a future clone.

Verified: rebuilt and confirmed via the compiled bundle that
`VITE_API_BASE_URL` resolves to `/api/v1` (not the old fallback) at
runtime; a real sign-in through port 80 alone succeeded end-to-end with no
second port needed. Full frontend suite (54 tests) and lint clean. Deployed.

## 2026-10-07 — Cache entries no longer expire on a timer; invalidated by actual KB changes instead

**Files:** `backend/app/config.py`, `backend/app/services/cache_service.py`,
`backend/.env.example`

User reported caching seeming to disappear after being away — traced to
TTLs expiring naturally (search/retrieval cache: 5 min; embeddings: 1 hour;
answers: 6 hours), confirmed via `redis-cli INFO` that Redis itself had been
up 36 days straight, so nothing was actually restarting.

Before raising these blindly, checked whether permanent caching would be
safe: the retrieval cache key already incorporates a `knowledge_generation`
counter that's bumped on document ingestion (`admin_ingestion_service.py`),
so updating the knowledge base already invalidates old retrieval cache
entries regardless of TTL. The answer cache is keyed on the exact rendered
prompt (question + retrieved context), so once retrieval picks up fresh
content after a KB update, the prompt text itself changes, naturally
missing the old cached answer too. Confirmed this chain by reading the
actual code, not assuming it — raising TTLs to "always" doesn't mean
stale answers survive a real content fix.

Changed the default TTL for all four cache types (default/search/
embedding/answer) from a fixed number of seconds to **no expiry** (`0` is
now the sentinel for "forever" — `CacheSettings` fields are `int | None`,
with `None` meaning no expiry; `write_json`/`push_bounded_json_list`
updated to skip the Redis-level expire call when `None`). Still
overridable back to a real TTL via the same env vars if ever wanted.

One caveat documented, not hidden: Redis itself has no persistent storage
configured (no volume in `docker-compose.yml`), so an actual Redis
container restart still clears everything regardless of this setting —
this fix addresses the reported scenario (reconnecting to an always-running
VM), not a host reboot.

Verified: full backend suite (288 tests, 1 pre-existing unrelated failure)
passes unchanged; confirmed live via `redis-cli TTL` on a real write that
the key now has no expiry (`-1`); confirmed no test hardcodes the old
default (all cache tests construct explicit `CacheSettings(...)` objects).
Deployed: image rebuilt, container restarted, confirmed the running
server's actual settings return `None` for all four TTLs.

## 2026-10-06 — Fixed "admin panel keeps loading, then refresh logs me out"

**Files:** `backend/app/database.py`, `backend/frontend/src/app/AuthContext.tsx`,
`backend/frontend/tests/sessionExpiry.test.ts`

Reported by the user directly. Root cause: every authenticated request
checks out a DB connection via `get_current_user`'s `Depends(get_db)`, and
that connection stays checked out for the request's *entire* duration —
including a 40-60s Ollama wait on a cache miss — because FastAPI only tears
down a yield-dependency once the whole request finishes, not when the
function body is done with it. With the default pool (`pool_size=5,
max_overflow=10` = 15 total), enough concurrent chat requests can exhaust
it, blocking unrelated requests like the admin panel's own auth check for
up to `pool_timeout` (30s) — looking exactly like "keeps loading."

Considered giving `get_current_user` its own short-lived session to release
the connection immediately, but caught in testing that this would silently
bypass `get_db`'s override: `test_auth.py`/`test_authorization.py` mock the
database via `dependency_overrides[get_db]` (including a plain `Mock()` for
`db` in several cases), and a hardcoded session would skip that mock
entirely. Reverted that change — confirmed via `git diff` it left
`auth_dependencies.py` byte-identical to before — and instead raised the
pool ceiling (`pool_size=20, max_overflow=20`) as the safe fix with zero
risk to the existing test-override pattern.

Second half of the symptom — "then refresh logs me out" — was a separate
frontend bug: `restoreSession` treated *any* failure from `/auth/me`
(including a timeout caused by the very pool exhaustion above) as proof
the token was invalid, wiping a perfectly good token on a transient hiccup.
Now only a confirmed 401 clears the stored session; anything else just
fails that one attempt and leaves the token in place for the next reload.

Verified: 2 new tests (restoreSession's 401-only logic, by source-pattern
since this logic lives inside a React hook with no component-rendering
harness in this suite) — 6 total in `sessionExpiry.test.ts`, 53 frontend
tests overall, no regressions. Backend: confirmed via `git show HEAD` that
the 4 failures seen in the full suite occur identically with the original,
unmodified `database.py` — pre-existing test-ordering flakiness, unrelated
to this change, not introduced by it.

## 2026-10-06 — Fixed a cross-user conversation leak on the same browser tab

**Files:** `backend/frontend/src/services/authStorage.ts`,
`backend/frontend/src/pages/AgentPage.tsx`, `backend/frontend/tests/sessionExpiry.test.ts`

Reported directly by the user: logging out of an admin account and signing
into an agent account on the same browser tab showed the admin's previous
conversation. Root cause confirmed in `AgentPage.tsx`: the chat thread was
cached in `sessionStorage` under one fixed, global key, cleared only by the
in-app "new conversation" action — never on logout. Since `sessionStorage`
is scoped to the browser tab, not to who's logged in, the next person to
log in on that tab inherited whatever conversation was cached there, which
can include real operational questions and answers.

Moved the key into `authStorage.ts`, alongside the access token, and made
`clearAuthSession()` remove both together — so every path that ends a
session (explicit logout, and the session-expiry handling added earlier
today) now also wipes any cached conversation. Verified with a real test:
set the conversation key, call `clearAuthSession()`, confirm both keys are
gone. Full suite: 53 frontend tests passing.

## 2026-10-06 — Fixed "connecting/disconnecting" reports: session expiry and a chat timeout bug

**Files:** `backend/.env.example`, `backend/frontend/src/services/apiClient.ts`,
`backend/frontend/src/app/AuthContext.tsx`, `backend/frontend/src/services/chatApi.ts`,
`backend/frontend/tests/sessionExpiry.test.ts`

Investigated reports of random "disconnections" by reading live production
logs first, not guessing. Found three real, confirmed causes:

1. **No refresh-token mechanism at all, and a 15-minute access token.**
   Confirmed via `grep` across the backend — only `/auth/signin` exists, no
   `/auth/refresh`. Logs showed exactly the symptom this causes: frequent
   repeated `auth_signin_succeeded` events, i.e. people getting silently
   logged out mid-session and having to re-authenticate.
2. **No global handling for an expired session almost anywhere in the app.**
   The shared API client only had a *request* interceptor (to attach the
   token); a 401 on any admin/stats/audit call just failed silently with a
   generic error instead of a clear "please log in again." Added a
   *response* interceptor that dispatches a `session-expired` event on any
   401 — except `/auth/signin`, since a 401 there means "wrong password,"
   not "expired session," and must not be confused with it. `AuthContext`
   now listens for that event, clears the session, and shows "Votre session
   a expiré. Veuillez vous reconnecter."
3. **The blocking `/chat` endpoint had a hardcoded 20s client-side timeout**,
   while live logs showed real generation legitimately taking up to 59.9s.
   Raised that one call's timeout to 120s (matching the backend's own
   `OLLAMA_REQUEST_TIMEOUT_SECONDS`) without touching the global 20s default
   used by faster admin/analytics calls.

Also raised `AUTH_ACCESS_TOKEN_MINUTES` from 15 to 60 — a config change, not
a redesign, but it directly cuts how often the forced-relogin disruption
even happens given there's no refresh token to fall back on.

Verified: 4 new tests, including a real (not just text-pattern) execution of
the interceptor logic — confirmed a 401 elsewhere dispatches the event, a
401 on signin does not, and the chat call's request config carries the
120s timeout. Full suite: 288 backend (1 pre-existing unrelated failure)
and 52 frontend tests, all passing. Confirmed live: new token lifetime
returns `expires_in: 3600` from a real sign-in call; verified the database
(users, knowledge_gaps, chat_sessions) survived the container restart
needed to pick up the new setting.

## 2026-10-02 — Third knowledge-gap signal: user-reported, via the existing feedback button

**Files:** `backend/alembic/versions/20261002_01_knowledge_gap_user_flagged.py`,
`backend/app/models.py`, `backend/app/services/knowledge_gap_service.py`,
`backend/app/feedback_routes.py`, `backend/app/admin_schemas.py`,
`backend/tests/test_feedback_workflow.py`,
`backend/frontend/src/features/admin/KnowledgeGapPanel.tsx`,
`backend/frontend/src/types/admin.ts`

The two automatic signals (model's wording, retrieval confidence) miss a real
case: sometimes the model confidently answers using a fragment of the
question without actually knowing the answer — no "information not found"
phrasing, no low-confidence retrieval, so neither automatic detector fires.

Rather than building a new chat UI button, wired the **existing** thumbs-down
feedback button (already in `AnswerPanel.tsx`, with reasons like "Réponse
incorrecte" / "Information manquante") into the knowledge-gaps system: any
non-"helpful" rating now also creates (or marks) a `knowledge_gaps` row, via
a new `user_flagged` boolean — a third independent signal, consistent with
the original two-boolean design. If an automatic gap already exists for that
message, it's marked `user_flagged=True` rather than duplicated.

Verified: 3 new tests (negative feedback creates a gap; helpful feedback
doesn't; negative feedback marks an existing automatic gap instead of
duplicating) plus the full suite (288 tests, 1 pre-existing unrelated
failure, confirmed present before this change). Frontend build + lint clean.
Migration applied to the live database and confirmed via `\d knowledge_gaps`.
`api` image rebuilt and redeployed; frontend rebuilt and redeployed.

## 2026-09-29 — Knowledge-gap tracking: a base of questions the chatbot couldn't answer

**Files:** `backend/alembic/versions/20260928_01_knowledge_gaps.py`,
`backend/app/models.py`, `backend/app/services/knowledge_gap_service.py`,
`backend/app/routes.py`, `backend/app/admin_routes.py`,
`backend/app/admin_schemas.py`, `backend/tests/test_knowledge_gap.py`,
`backend/frontend/src/features/admin/KnowledgeGapPanel.tsx`,
`backend/frontend/src/pages/AdminPage.tsx`,
`backend/frontend/src/components/layout/AdminSidebar.tsx`,
`backend/frontend/src/services/adminApi.ts`, `backend/frontend/src/types/admin.ts`

Built the requested feature: a database of questions the chatbot could not
actually answer, so the missing information can be found and added to the
knowledge base.

Detection uses two independent signals, stored as two separate boolean
columns (`text_indicates_missing`, `low_confidence`) rather than a single
merged flag, so each is visible on its own:
- `text_indicates_missing`: the generated answer text matches one of the
  known "information not found" phrasings the model is instructed to use
  (see `MISSING_INFO_PHRASES` in `knowledge_gap_service.py`).
- `low_confidence`: the retrieval confidence label returned alongside the
  answer is `low` or `unknown`.

A row is recorded whenever *either* signal fires, from both `/chat` and
`/chat/stream` (wrapped in `try/except: pass` so a logging failure can
never break a real answer, matching the existing pattern used for
assistant-message logging in the same routes).

Added an admin surface to work the list:
- `GET /admin/knowledge-gaps` (filter by status, paginated)
- `POST /admin/knowledge-gaps/{gap_id}/resolve` (mark resolved/dismissed,
  with resolution notes)
- A new "Questions sans réponse" page in the admin sidebar: a filterable
  table plus a detail dialog to record what was fixed.

Verified in layers:
- 13 new backend tests (detection heuristics, service CRUD, admin route
  auth/404 handling) plus the full existing suite (285 tests) — one
  pre-existing, unrelated failure in `test_chat.py` confirmed present
  before this change and untouched by it.
- Frontend: `tsc -b && vite build` and `eslint .` both clean.
- Migration applied to the real database and confirmed via
  `information_schema.columns`.
- Full real round-trip (insert → list → resolve) run directly against the
  live database and the live FastAPI app through the actual service and
  route code, then the test row was deleted immediately afterward so it
  doesn't show up as noise for whoever triages this list — the live
  chatbot pipeline itself was deliberately not used for this check, to
  avoid writing a synthetic question into data a manager will actually
  review.
- `api` image rebuilt and redeployed; frontend rebuilt and copied to the
  nginx-served path.

_Commit: `adc5ad4`_

## 2026-09-23 — Semantic (fuzzy) answer cache for paraphrased questions

**Files:** `backend/app/config.py`, `backend/app/services/cache_service.py`,
`backend/app/services/ollama_service.py`, `backend/tests/test_chat.py`,
`backend/tests/test_phase4b_performance.py`

Tested and confirmed the exact-match answer cache from the previous entry
doesn't help at all for a paraphrase — "Quel est le code situation..." vs
"Quel code situation utiliser..." hashes to a completely different key
despite meaning the same thing, so it still pays the full ~25-45s
generation cost. In practice agents rarely type the exact same sentence
twice, so this mattered.

Added a second, fuzzy layer on top: on an exact-cache miss for a
standalone question (no conversation history — a context-dependent
follow-up is never matched against an unrelated cached turn), embed the
question and scan a small, bounded, TTL'd Redis list of recently-answered
questions (`CACHE_ANSWER_SEMANTIC_SIZE`, default 100) for a cosine-
similarity match above `CACHE_ANSWER_SEMANTIC_THRESHOLD` (default 0.93).

The threshold came from real measurements, not a guess: true paraphrases
of the same question scored 0.946-0.991 cosine similarity; genuinely
different questions — even ones sharing the same "quel code..." sentence
structure — scored only 0.795-0.820. 0.93 sits with a wide, measured
margin on both sides.

Verified live against the real embedding model:

| | Time |
|---|---|
| Original question | ~41,357 ms |
| Paraphrase of it | **2 ms**, identical answer |
| A genuinely different question (same "quel code..." structure) | ~64,623 ms — correctly NOT matched |

Added `push_bounded_json_list()`/`read_json_list()` to `cache_service.py`
(same fail-open behavior as every other cache helper here) for this first
cache use case needing a bounded list rather than a single key. Full test
suite (272 tests) passes; image rebuilt and redeployed.

_Commit: `2f05b78`_

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
