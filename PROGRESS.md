# Progress

A running log of changes made to this repository, most recent first.

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
