# Progress

A running log of changes made to this repository, most recent first.

## 2026-10-16 (3) — Processes 3-7/N: RF Soir, Erreurs PIDI, Setting VE, F04/P03, SBL

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

Checked all 5 remaining processes with the same rigor as the first two
before assuming "self-contained, lower risk" from the initial survey was
actually true:

- **RF Soir, Setting VE (both sub-tables)**: re-checked the raw sheets for
  hidden sub-tables or composite keys -- genuinely clean, already correctly
  extracted. Verified live with realistic queries, both answer correctly.
- **F04/P03, SBL**: confirmed both sheets are 100% empty cell grids (no
  real cell data at all, pure screenshots) -- rules out the one failure
  mode that actually bit this project before (a real table hiding under a
  screenshot, as on `Expertise & Fiabilisation`). Two queries that first
  looked like failures turned out to be bad test phrasing on my part, not
  product bugs -- retested with phrasing matching the real key text and
  both answered correctly and completely.
- **Erreurs PIDI (flèche rouge)**: real bug, same root cause as the
  vandalism fix -- `type_erreur` is the full 60-200 character French error
  message PIDI displays, which no real agent would retype verbatim. A real
  agent types the PID code shown on screen (e.g. "PID-1236") instead. Added
  `code_pid`, parsed from the message text, as an additional key field.
  Two PID codes (PID-1236, PID-2001) genuinely label two different rows
  each -- confirmed these correctly stay declined (ambiguous) rather than
  guessing, same inference-pass safety as before. Hit and fixed a second,
  narrower bug getting there: "PID-1205.2" doesn't tokenize under the
  shared `_TOKEN_RE` (the decimal point splits it into two tokens), so
  widening that shared regex risked side effects everywhere else it's used
  -- added a narrow, additive PID-code pattern to `_candidate_tokens`
  instead, scoped to just this one known domain pattern.

Full regression (15 cases) passes clean. `lab_api` rebuilt once (the PIDI
fix needed a code change for the tokenizer; RF Soir/Setting VE/F04-P03/SBL
needed no changes at all).


## 2026-10-16 (2) — Process 2/N: Facturation Cuivre/FTTH, GESTAR, Lot et Chantier
## 2026-10-16 (2) — Process 2/N: Facturation Cuivre/FTTH, GESTAR, Lot et Chantier

**Files:** `backend/app/services/decision_lookup_service.py`

Continuing the process-by-process rebuild. Mapped the real "Facturation"
process before touching code, same discipline as the SAV+ cluster:

- `Facturation Cuivre` is one sheet with two parallel views of the same
  billing logic, confirmed by reading the raw cell layout -- a clean
  "Activité -> Article" list (cols AB:AD, 23 rows) and a checkbox matrix
  (cols G:Z, 56 rows). For most activités the matrix genuinely has several
  competing rows (ambiguous on its own, correctly left alone), but for a
  handful (confirmed: MIT and others) it has exactly one -- and that one
  legitimately-resolving row was triggering the tier's "two tables resolved
  = ambiguous, decline" safety rule even though both tables agreed on the
  same fact. This is exactly how the "MIT" regression from the last round
  happened. Added `_lookup_facturation_cuivre_merged()`: tries the clean
  table first, then checks the matrix for the same activité -- merges into
  one richer answer when they agree, flags an explicit conflict (same
  pattern as the EXC flag) if they don't, and otherwise defers to the
  existing generic path unchanged. `Facturation FTTH` has no such twin
  table (checked -- confirmed it's matrix-only), so this only applies to
  Cuivre.
- `GESTAR` (Dommage réseau billing: code_releve + conditions -> article +
  lot + chantier, already self-contained in one row) and `Lot et Chantier`
  (zone + activité -> lot/chantier, for the non-GESTAR billing path) were
  checked directly against real queries -- both already worked standalone,
  no fix needed.
- Added a reminder note to every Facturation Cuivre/FTTH activité answer:
  Lot/Chantier (needed to actually route the billing ticket) lives in a
  separate table keyed by zone, which a bare activité question usually
  doesn't name -- can't auto-resolve it without a zone in the question, so
  it's surfaced explicitly rather than silently left out.

Full regression (13 cases) passes clean, including the "MIT" case that
regressed last round. `lab_api` rebuilt once.


## 2026-10-16 — Real agent testing found 3 failures; root-caused and fixed all 3
## 2026-10-16 — Real agent testing found 3 failures; root-caused and fixed all 3

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

An actual agent tested the new KB live and reported 3 bad answers. Explicit
instruction from this: stop patching symptoms, go process by process --
collect everything about a process, build its real pipeline, not another
isolated table. Root-caused all 3 with evidence before changing anything
(no guessing):

1. **"REO AI" (Réaffecté BL) → "cas reconnu", nothing else.** Not a weak
   answer -- the table (`FDE - Situations justifiant une mise en Réaffecté
   BL`) was extracted with `value_schema: []`, a pure list with nowhere to
   attach a value. Found the real connection on the same sheet: a sibling
   ticket row ("FDE - Mise en Réaffecté BL GO GSS") whose own motif text
   says, literally, "Lorsqu'une situation justifie une mise en Réaffecté BL
   il faut historiser pour assurer le pilotage" -- i.e. that one ticket IS
   the action for every situation in the list, stated in its own wording,
   not inferred. `extract_ticket_reaffectebl()` now attaches it to all 16
   situation rows.
2. **"client Absent" (SAV+ Expertise) → consigne only, no GEM-eligibility
   context.** Checked whether this table should be merged with its sibling
   "SAV+ Fiabilisation" table -- it shouldn't: the source sheet's own column
   headers ("Fiabilisation" / "Expertises") mark them as parallel
   vocabularies for two different phases of the same case, not joinable
   rows (confirmed, not assumed). The real gap: the chatbot answered in
   isolation from the GEM-eligibility and LBE/non-LBE pieces of the same
   SAV+ process. Added a static process-context note (no fabricated link,
   since the row text itself doesn't reference them) to every answer from
   the 4-table SAV+ Fiabilisation/Expertise cluster, pointing at GEM
   eligibility (incl. the known EXC conflict) and the LBE/non-LBE branch.
3. **"PB vandalisé sans code de décharge, peut-on clôturer?" → no match at
   all.** The real, correct answer ("numéro de décharge OBligatoire, sinon
   Réaffecté BL") was already sitting in `FDE - Référentiel des échecs`,
   never previously extractable: one row on that sheet jams 3 échec codes
   (VB/BF/LB) into one 160-character `type_echec` string, which the generic
   matcher's substring rule can never match against a real question. Split
   that row into 3 clean VB/BF/LB rows using the sheet's own embedded
   legend text (not invented), and added a `code_echec` short-code field to
   all 47 rows. That alone wasn't enough -- the question still never says
   "FTTH" explicitly, and `technologie` is a required key field -- so also
   added a bounded inference pass to `_generic_table_lookup`: a key field
   left unresolved by text is now accepted if the fields that DID resolve
   via real text already narrow the table to exactly one value for it (still
   declines on any remaining ambiguity -- never guesses). Scoped to Tier 1
   only after finding it created a new Tier-2 collision ("MIT" started
   matching two different Facturation tables that both legitimately resolve
   once inference is unscoped) -- Tier 2/3 are this file's own
   documented highest-collision-risk tables, so inference stays off there.
   Even after the échec fix, the actual question matched a *different*,
   pre-existing table (`SAV FTTH - Codes de clôture`, via the same inference
   pass) that has a closure code but no décharge field at all -- added a
   targeted static note citing the real fact from `FDE - Référentiel des
   échecs` rather than forcing a fake cross-table link where the source
   text doesn't actually reference the other table.

47 rows now in `FDE - Référentiel des échecs` (was 45). 33 decision tables,
1227 rows total. Full regression (13 cases, including all 3 original
failures) passes clean. `lab_api` rebuilt 3 times across this round, the
first two each catching a problem (an incomplete fix, then the MIT
collision) before the final clean pass.


## 2026-10-15 — EXC GEM-eligibility contradiction: dug deeper, couldn't resolve it, flagged it instead

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

Explicit follow-up instruction to attempt resolving the EXC contradiction
left open by the decision-tree remap (below). Tried substantially harder
than the first pass before concluding it's unresolvable from the workbook
alone:
- Re-extracted real image anchor coordinates straight from the drawing XML
  (openpyxl's `ws._images` silently returned 0 images on this reload --
  parsed `xl/drawings/drawing9.xml` directly instead). Confirmed the
  flowchart image overlapping the real-cell table (rows 64-83, media
  `image18.png`) is an unrelated "PFO PCC PROCESS SAV+" fiber-box repair
  procedure, and the BtB/Hors-BtB matrix screenshot (`image24.png`, image 13
  of 14) is anchored rows 90-109 -- nowhere near the contested table. Viewed
  both images directly to confirm.
- Tested whether the real-cell table could be "just the BtB column" of the
  matrix, using the other activité codes both tables share (PFO, PPC, ADI,
  CPC, PCC) as a cross-check. Doesn't hold -- the real table's own internal
  pattern pairs PFO~PPC~ADI together (mostly OUI) and CPC~PCC together
  (mostly NON), which doesn't match the matrix's hand-transcribed grouping
  ("PFO/PCC", "PPC CPC"). New, previously undocumented finding: this
  suggests the *screenshot's* transcription may have transposed PCC and
  PPC -- a second open question, not assumed or fixed.
- Checked all 28 columns around the real table for a hidden canal split
  (none), cell comments (none), and fill/font colours on the EXC row vs its
  neighbours (ordinary alternating-row banding, nothing EXC-specific).
- Checked whether `FDE - Aléas normés` might hold an EXC-specific override
  explaining the real table's all-NON pattern -- it's keyed by échec
  typology only, no activité-level entries at all.

Explicit decision from this point: don't pick a winner. Loaded the real
table into the schema as its own decision table (`Expertise & Fiabilisation
- Durée aléa GEM standard par activité (AB/RF/TC/MC/BL)`, 30 rows, 6
activités x 5 échecs, in `extract_decision_tables.py`) instead of leaving it
undocumented data, and added `_sav_fiabilisation_conflict_note()` to
`decision_lookup_service.py`: when `_lookup_sav_fiabilisation_matrix`
answers for an activité that this new table says is NON for *every* échec
type while the matrix says Oui for either canal (the one pattern actually
proven to conflict -- checked this doesn't false-positive on ADI/PFO/PPC,
which the new table mostly allows), the answer now appends an explicit
"⚠ Conflit de sources non résolu" note with both values instead of silently
returning only the matrix's. Verified live: `EXC` now shows the conflict
warning; `ADI` (same sheet, same table, not the proven conflict pattern)
still answers cleanly.

33 decision tables now, 1225 rows. Full regression (10 cases) passes clean.
`lab_api` rebuilt and restarted once for this round.


## 2026-10-15 — Full decision-tree remap: tables aren't independent, modeled the links

**Files:** `excel-sources/DECISION_TREE_MAP.md`,
`backend/alembic/versions/20261015_04_decision_table_links.py`,
`backend/app/models.py`, `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

Explicit instruction to stop patching individual gaps and properly understand
the workbook as what it actually is: multiple interconnected decision
processes, not 31 independent lookup tables. Redid the remap from scratch --
every sheet's cells, formulas, *and* image anchor positions (not just image
content, but where each image actually sits on the sheet) -- documented in
`DECISION_TREE_MAP.md`. Searched every decision_table_row already loaded for
"voir X" cross-reference phrases rather than relying on spotting them by eye.

**Confirmed real findings:**
- `GEM Cuivre`'s own output text says, on 24 of its 176 rows, literally
  "re-inject without an appointment, see the re-injection consigne" -- a
  genuine pointer to a *different* table (`RDV-REINJECTION-CONSIGNES-008`),
  not a final answer. Same pattern found in `GEM FTTH`, pointing to both the
  RDV table and `FDE - Aléas normés`.
- "Avec RDV / sans RDV" is a real, recurring branch point confirmed across 5
  independent sheets -- in one of them (`CODE SAV FTTH CLOTURE`) it's proven
  to directly decide RMC vs ABS for the same underlying case. It is NOT,
  however, a key in the GEM-eligibility tables themselves (checked directly)
  -- so it can't be used to resolve a GEM question by inference alone.
- A genuinely new branch point, never modeled before: `Expertise &
  Fiabilisation`'s "Levier Wholesale" screenshot says a line's LBE/non-LBE
  status decides whether the agent stays in the SAV Fiabilisation process
  (code FCDx) or switches entirely to a separate SAV Incident process (code
  SAVCx). Built as decision table #32, `FTTH SAV+ - Levier Wholesale`.
- **An unresolved, confirmed inconsistency, left unresolved rather than
  guessed at**: two real (non-screenshot) tables on `Expertise &
  Fiabilisation` give opposite GEM-eligibility answers for EXC. Checked
  whether image-anchor position explained it (e.g. a Wholesale/non-LBE
  scope) -- it doesn't; the nearest image is an unrelated test-procedure
  diagram. Documented as a question for whoever owns the real process, not
  resolved by inference.
- Systematic check (compared each extraction script's row range against the
  sheet's actual last non-empty row) confirms this "hidden second table"
  problem is isolated to the one sheet built from a screenshot transcription
  rather than direct cell reading -- no other decision table has the same gap.

Added `decision_table_links` (source table -> target table -> trigger
description + the exact source text pattern that fires it) and wired it into
the GEM Cuivre/FTTH answer formatters: when a matched row's text contains a
known link pattern, the chatbot's answer now explicitly says "→ Voir aussi :
« [table name] » ([why])" instead of leaving the pointer buried in raw
French text the old system just repeated verbatim without acting on it.

Added a 4th link, found by the same systematic "voir" search: `GEM FTTH` ->
closure table when échec = TVC ("TVC / voir code clôture pour la situation",
15 rows). Initially ambiguous between two candidate closure tables (`FTTH
Production Hors IHX LMX` vs `FTTH Accès/Service`) -- linked to the former on
activité-vocabulary overlap only, with the ambiguity documented rather than
hidden. **Since resolved with direct textual proof, not inference**: the
same TVC row's commentaire explicitly instructs "+ code famille : TC", and
column-by-column inspection of both candidate sheets shows only `FTTH
Production Hors IHX LMX` (sheet `CODES PROD FTTH Cloture`) has a `famille`
column at all -- `FTTH Accès/Service` (sheet `Codes clôture FTTH`) has none.
Its one matching row (cause="Elagage Privatif") has famille="TC" +
code_situation_retail="TC" + cloture="TVC/.. après GEM", an exact match.
Cross-checked against sheet titles too: `GEM FTTH`'s own header reads
"Activité Fibre **Production**"; the resolved target's sheet header reads
"**PRODUCTIONS** FTTH HORS IHX LMX (pose de box)" -- same scope. The other
candidate is scoped "Accès (Raccordement ou dépannage de ligne)", a
different activity entirely, even though it coincidentally also has an
"Elagage Privatif" row. `trigger_description` for link #4 updated in place
(DB data change, no code/schema change, no rebuild needed) to record this
resolution and the evidence for it. Also extended `_linked_table_hints`
from the two bespoke GEM formatters to the generic path
(`_format_generic_answer`/`_generic_table_lookup`), so all 32 tables
surface known links, not just GEM Cuivre/FTTH.

32 decision tables now, 1195 rows, 4 links. Full regression (9-13 cases
across reruns) passes clean after each rebuild, including the final one
with the generic-path link wiring. `lab_api` rebuilt and restarted 4 times
across this round.


## 2026-10-15 — Fixed the old RAG fallback content too (SBL-TRAIT-029, F04-P03-003)

**Files:** `backend/data/processed/chunks.json`, `backend/scripts/fix_sbl_f04_chunks.py`,
`backend/scripts/upsert_milvus_fix.py`

Building the corrected decision tables for these two articles doesn't remove
the old wrong facts from the live RAG fallback -- any question that doesn't
hit the new table's exact key match still falls through to `chunks.json`/
Milvus, which still said PBCF5 and had the REO/VA misattribution. Since the
new KB is now built, this closes that gap: patched the 32 affected chunks
directly (hand-corrected per chunk, not a blind find-replace -- the SBL fix
is structural, not a typo, so "REO/VA" needed moving to the right tier in
each chunk, not just a text swap).

Getting this into the live Milvus collection wasn't straightforward:
`scripts/embeddings.py --write-milvus` turned out to use field names (`vector`)
that don't match the real live collection schema (`embedding`), confirmed via
`describe_collection` -- that script is stale, not what actually built the
running index. `scripts/load_embeddings_to_milvus.py` has the right schema
but defaults to dropping and rebuilding the *entire* collection, which is
far too destructive for a 32-row fix. Used `embeddings.py` only for its
(correct) embedding-generation logic, output to a file instead of Milvus,
then wrote a small surgical upsert (`upsert_milvus_fix.py`, real
`MilvusClient.upsert`, matching the actual schema) touching only those 32
rows by ID. Also updated the corresponding 32 rows in Postgres `chunks` for
consistency with the admin UI.

Verified end-to-end through the real `search_chunks()` function the live
chatbot calls, not just a direct Milvus query: a search for "absence signal
box" now returns the corrected PBCF3 text. Zero `PBCF5` remaining in
F04-P03-003; the one remaining `PRO/OR` string in SBL-TRAIT-029 is an
intentional correction note ("confirmed PRO/QR, not PRO/OR"), not a leftover
error.


## 2026-10-15 — Phase 5: kb_articles, completing the full new KB (30/30 articles)

**Files:** `backend/alembic/versions/20261015_03_kb_articles.py`,
`backend/app/models.py`, `backend/scripts/populate_kb_articles.py`

Added `kb_articles` -- the narrative-content half of the clean KB, completing
what Phase 2-4 only did for the tabular half. One row per article (all 30),
`content_scope` marks whether `narrative_content` is the full article (7
articles with no decision table at all: FDE-ACT-002, FDE-ALEA-RF-030,
FDE-TEST-JOKER-020, GESICA-CLOT-024, IGB-TRT-004, KB-INFO-001, RPR-TRAIT-026)
or just a short intro (the other 23, whose operational facts live in
decision_tables joined via kb_article_tables).

Content comes from `chunks.json`, but not copied blindly -- only the chunk
types that carry facts (generic, key_points, business_case, rule); question/
faq chunks skipped as redundant restatements already verified faithful
during today's proofreading pass. The one confirmed error in this content
(IGB-TRT-004's "technicien DI" -> "Technicien D3", per the real screenshot)
is corrected in the population script itself. `SBL-TRAIT-029` and
`F04-P03-003` get `content_scope: intro` now that they're table-backed, so
their old wrong facts (the REO/VA misattribution, PBCF5) aren't carried into
`kb_articles` at all -- only their résumé paragraph is, and the real facts
come from the two decision tables added earlier today.

All 30 articles populated, nothing empty (shortest is 317 chars, an intro;
longest is 17,235 chars, FDE-ACT-002's full content).

This completes the full new KB envisioned at the start of this project:
5 glossary tables, 31 decision tables (1193 rows), and now kb_articles for
every article's narrative content -- all in Postgres, all additive. The live
chatbot still serves exclusively from the old chunks.json/Milvus RAG path;
nothing has been cut over yet, per explicit instruction to leave the current
system untouched until this work is finished.


## 2026-10-15 — 3 more decision tables from the OCR proofreading pass, and an accent-folding fix

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

Follow-up to proofreading the 17 screenshot-sourced articles against their
real screenshots. Three findings became three new decision tables instead of
chunk-level patches, continuing today's actual architecture rather than
reaching back into the old RAG pipeline:

- **`ALEA-RF-SOIR-011`** turned out to have a real Excel table behind it after
  all (`TRAITEMENT RF SOIR`, rows 19-25) that Phase 2 missed entirely --
  confirmed all 6 rows match the article's existing rules exactly, so this
  one was just a missed table, not a content bug.
- **`F04-P03-003`** and **`SBL-TRAIT-029`** are screenshot-only (no real Excel
  cells), hand-transcribed the same way the EXC/IDV matrix was. Both fix real
  errors found in the proofreading pass: F04-P03-003's "Absence signal box"
  had the wrong code (`PBCF5` in the old generated text; the real screenshot
  shows `PBCF3`, same code as "Pb casse voisin", which the screenshot
  explicitly says is intentional). SBL-TRAIT-029 had a systematic
  misattribution -- the REO/VA and PRO/QR closure codes (which only apply to
  the ">threshold" rows) had leaked onto every "<threshold" rule too, and
  PRO/QR was mistyped as PRO/OR -- found to affect 25 of that article's 53
  chunks once actually counted (not "3 chunks" as first estimated -- this KB
  restates each fact across generic/key_points/business_case/rule/faq chunk
  types, so one wrong reading echoes many times).

31 decision tables total now. Also fixed a real usability bug found while
testing these: `_match_field`'s exact-token path didn't accent-fold (only
the substring path did), so a single-word accented candidate like "Affectés"
silently failed to match "affectes" typed without an accent -- common when
typing fast. Added `_fold_accents()` (NFKD-normalize, drop combining marks)
applied consistently on both match paths now.

Deliberately NOT touched: the live chunks.json/Milvus RAG pipeline that the
current chatbot still serves from. Per explicit instruction, this is building
a complete separate "new KB" (decision tables + an upcoming `kb_articles`
table for narrative content) that doesn't replace anything live until it's
finished.


## 2026-10-15 — Facturation Cuivre/FTTH: extracted the matrices, then found and fixed 3 collision bugs

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

Closed the one deliberately-skipped gap from Phase 2. Both sheets turned out
different from each other: `Facturation Cuivre` has a clean side-table
(Activité -> Code Clôture -> Article, in columns AB:AD, separate from the
matrix) plus a checkmark matrix; `Facturation FTTH` is pure matrix, no clean
side-table, and its cells hold categorical values ("Immeuble"/"Aérien
Aéro-sout Facade"/"Sous-terrain"), not just checkmarks. Both matrices bundle
several activité codes under one column header (e.g. `"EXB\n-\nEXC\n-\nEXP\n-
\nSi produit DSL, à traiter comme PFE"`). Wrote a conservative splitter: a
line only counts as code(s) if every space-separated token on it is fully
uppercase/code-shaped; anything else is kept as a note rather than guessed at.
The full original header text is preserved alongside the split codes either
way, so nothing is lost even where the split under-captures. 3 new decision
tables, 294 rows (23 + 56 + 215).

Wiring these into the chat lookup broke the flagship EXC/IDV case three
separate times before landing correctly -- each one caught by testing the
actual pilot scenario, not by trusting the row counts:

1. **Numeric keys crashed the matcher** -- billing codes like `2418`/`6310`
   are stored as numbers, not strings; `_match_field` assumed `.strip()`
   existed on every candidate.
2. **A 3-word code fell through a gap** -- `"R02 hors REH"` (12 chars) was
   too short for the long-text substring tier (>15 chars) but couldn't match
   via exact-token either, since token generation only produces bigrams, not
   trigrams. Root cause was using *length* as the tier boundary instead of
   *"does it contain a space"* -- a 3-word phrase needs the same verbatim-
   substring treatment as a long free-text key regardless of its length.
3. **The flagship sentence regressed, twice** -- adding Facturation made
   `"comment clôturer EXC..."` start colliding between the GEM-eligibility
   answer and a billing-article answer for the same bare code "EXC" (both
   real facts, but the question is clearly about clôture, not billing). Fixed
   by tiering instead of a flat priority list: GEM tables first (including
   folding the SAV+ matrix into the *same* bespoke Cuivre/FTTH perimeter
   logic as the other two GEM tables, since it has the identical Cuivre/FTTH
   collision risk -- e.g. "MIT" and "IDV" both exist, meaning different
   things, in both perimeters), then other operational tables, then
   Facturation, then the bare code->description glossaries last. Each tier
   is only consulted if the previous one found nothing.

Also found a genuine extraction bug on the already-live `Activité FTTH`
table while regression-testing: rows 26/28 ("Sans RDV"/"Avec RDV") are
sub-section labels sitting in the activité-code column, not real codes --
confirmed by direct inspection and excluded explicitly (not via a general
"no description" filter, which would have also dropped legitimate codes like
"IH(x) sauf IHD").

Full regression suite (13 cases spanning every tier, the original pilot
sentence, and multiple genuinely-ambiguous bare codes) passes clean.
`lab_api` rebuilt and restarted 5 times across this change.

## 2026-10-15 — Built the EXC/IDV GEM-eligibility matrix as a real decision table

**Files:** `excel-sources/extract_decision_tables.py`,
`backend/app/services/decision_lookup_service.py`

The one gap flagged at the end of the last Phase 4 entry: `EXC` was never a
row key in any decision table, because its only source is the
`Expertise & Fiabilisation` screenshot matrix (Production/Maintenance x
BtB/Hors BtB GEM eligibility), which Phase 1 had only partially captured
(into `activite_codes.family` text, not queryable rows). Re-read that
screenshot carefully and hand-transcribed all 21 cells (9 Production + 12
Maintenance activités) into a 25th decision table, `source_type: "screenshot"`
-- the one table in this project without real Excel cells behind it, flagged
explicitly in its description as read-by-eye and worth a business spot-check
on a contested case, unlike every other table here (read programmatically).

Wired into the generic lookup. The literal original pilot sentence --
"comment clôturer EXC sans rdv en abs" -- now resolves for the first time
through this path (previously fell back to RAG every time, since no
decision table had EXC as a key at all).

Found one more extraction bug while testing that exact sentence: it kept
returning None even though bare "EXC" alone worked. Root cause -- the
"Activités Production FTTH" table had a spurious entry literally coded
`"Sans RDV"` (confirmed by direct inspection: rows 26/28 of that sheet are
sub-section labels sitting in the code column, not real activité codes,
unlike every other blank-description row in that sheet which *is* a real
code like "IH(x) sauf IHD"). The bigram "sans rdv" in the question matched
that spurious entry, so two tables resolved at once and the ambiguity-safety
check (correctly) declined to answer. Excluded the two known-bad values
("Sans RDV", "Avec RDV") explicitly rather than inventing a general filter
that risked dropping legitimate codes too.

Full regression pass across every case tested in this phase (EXC, IDV in
both perimeters, bare IDV/MIT correctly declining, RDV consignes, VE codes,
Lot et Chantier, R02 now correctly ambiguous against the new matrix table
too) all passed. `lab_api` rebuilt and restarted twice (new table, then the
artifact fix) to apply.


## 2026-10-15 — Wired the remaining 22 decision tables into the deterministic lookup

**Files:** `backend/app/services/decision_lookup_service.py`

Extended `find_decision_table_answer()` beyond the two GEM tables to all 24
decision tables loaded in Phase 2. Rather than 22 bespoke lookup functions,
added one generic matcher: every field in a table's `key_schema` must resolve
to exactly one candidate found in the question (exact token match for short
codes like échec/région/zone/activité; exact verbatim substring match for
long free-text keys like a "cause" description or a PIDI error message), or
the table is skipped. Long-text keys will rarely fire in practice (an agent
would need to paste the near-exact phrasing), but that's the honest tradeoff
-- a loose/fuzzy match on free text is exactly the embedding-similarity
problem this project exists to avoid, so it stays strict rather than fuzzy.

Testing surfaced a real bug before shipping it: a bare "IDV" with no échec
and no perimeter signal -- exactly the under-specified case the GEM lookup
correctly declines -- fell through to the generic tier and silently answered
using only the Cuivre-side "Activités Production Cuivre" glossary entry,
ignoring that IDV is also a distinct FTTH code. The initial design returned
the first table (by priority order) that resolved; fixed by collecting every
table that resolves and only answering when exactly one does. A second table
also matching now correctly means "ambiguous, decline" instead of "first one
wins" -- same principle as the GEM perimeter check, just generalized.
Verified: "IDV" alone and "MIT" alone (also ambiguous across tables) now both
return None; specific questions (RDV consignes by techno+région, FDE VE
codes, Lot et Chantier by zone+activité, "R02" alone where it's unambiguous)
all resolve correctly.

`lab_api` rebuilt and restarted twice (once per fix) to apply.


## 2026-10-15 — Phase 4 of the clean-schema project: deterministic GEM-eligibility lookup wired into chat

**Files:** `backend/app/services/decision_lookup_service.py`, `backend/app/routes.py`,
`excel-sources/extract_decision_tables.py`

Added `find_decision_table_answer()` and wired it into both `/chat` and `/chat/stream`,
ahead of `generate_answer_with_ollama`/`stream_answer_with_ollama`: if the question names
exactly one activité code (from `activite_codes`) and an unambiguous perimeter (Cuivre vs
FTTH — resolved from the code itself when it only exists in one perimeter, or from an
explicit "cuivre"/"fibre"/"ftth" signal in the question when it exists in both, e.g. `IDV`),
plus an échec code that's a real key in that perimeter's GEM decision table, the answer comes
straight from `decision_table_rows` — no embeddings, no reranking, no LLM call. Anything that
doesn't resolve fully (ambiguous perimeter with no signal, unrecognized échec, more than one
activité code named) returns `None` and falls through to the existing retrieval+generation path
unchanged. New `generation_provider: "decision_table_lookup"` value, `confidence: "high"`.

Manually verified (no pytest available in the production image — it's deliberately slim, no
dev deps, and reinstalling the full ML stack to run the suite wasn't worth the time for this
change): `IDV + ABS + retails + cuivre` → "Code situation AB" / 7 jours ; the *same* `IDV + ABS`
but with `fibre` instead → a completely different, correct answer, "RMC" / 3 jours. That's the
perimeter disambiguation the EXC/IDV pilot bug needed.

Found and fixed 3 bugs in the Phase 2 extraction while building this, by testing the exact
pilot scenario rather than trusting the row counts: `Setting Fibre abrftcmc` and
`Setting Consigne re-injection` turned out to have the same "legend-only column" trap as
`Setting PRODCUIVRE` (activité/techno/région only populated in the sheet's first few legend
rows; the real per-row value lives in a composite text column) — both were silently extracting
`echec: None` / mangled `techno` values until a direct lookup test caught it. `Setting Echecs`
had the same trap on its "Technologie" column. All three now parse the real composite text
instead. Re-extracted, reloaded (854 rows, same counts as before — only the broken keys changed).

**Important limitation, found by testing rather than assumed**: the original pilot example,
"comment clôturer EXC sans rdv en abs", still does *not* resolve through this lookup — `EXC`
genuinely isn't a row key in the FTTH GEM table (`Setting Fibre abrftcmc`); it only exists in
the `Expertise & Fiabilisation` screenshot matrix, which isn't a `decision_table` yet (only its
BtB/Hors-BtB eligibility was captured into `activite_codes.family` during Phase 1). That exact
question still falls back to RAG, which is fine — it's the path already fixed by the
2026-10-13 retrieval-reranking change. What this phase fixes is the broader, Excel-backed class
of "activité + échec [+ canal]" questions, including correctly telling apart `IDV`-Cuivre from
`IDV`-FTTH, which was directly responsible for part of the original mix-up.

Not yet wired: the other 22 decision tables (Setting Echecs, Alea Normés, the closure-code flat
tables...) are loaded and correct but not yet queried by the chat pipeline — natural next step,
same "resolve fully or return None" pattern. `lab_api` rebuilt and restarted to apply.

## 2026-10-15 — Phase 2 of the clean-schema project: decision tables from the real Excel

**Files:** `backend/alembic/versions/20261015_02_decision_tables.py`,
`backend/app/models.py`, `excel-sources/extract_decision_tables.py`,
`backend/scripts/load_decision_tables.py`, `excel-sources/SHEET_MAP.md`

Added `decision_tables` / `decision_table_rows` / `kb_article_tables` and
populated them by reading the real Excel workbook directly (not the DOCX/chunk
intermediate) for the 9 formula-driven VLOOKUP tables plus the already-audited
flat tables (`Codes clôture FTTH/Cuivre`, `Gestar`, `+ TICKET REAFFECTEBL`,
`LOT ET CHANTIER`, `CODE SAV FTTH CLOTURE`, activité/produit reference lists).
24 decision tables, 854 rows total, each row traceable to the sheet and
columns it came from.

Building the extraction surfaced and fixed a second wrong finding from the
2026-10-14 audit: `SHEET_MAP.md` had described `Setting code de clôture SAV`
as one table shared between `FTTH-FIABILISATION-CLOTURE-007` and
`SAV-CLOT-016` (flagged then as a drift risk). Reading the real columns during
extraction shows it's actually **three independent sub-tables living in
different column ranges on one physical sheet** (D:G → SAV-CLOT-016 only;
J:M and P:S → FTTH-FIABILISATION-CLOTURE-007 only) — there was never any
duplication between the two articles. `SHEET_MAP.md` corrected accordingly.

Two sheets (`Facturation Cuivre`, `Facturation FTTH`) turned out to be visual
matrices (activité columns x échec rows with checkmarks) rather than
row-per-record tables. Deliberately excluded from this pass rather than risk
misreading a merged layout — flagged in `SHEET_MAP.md` for a dedicated pass.

Verified post-load: looking up `activite=IDV, echec=ABS` in the Cuivre GEM
table returns "Code situation AB" for both canals, matching the real sheet
exactly — this table is what Phase 4 (wiring a deterministic lookup into the
chat pipeline, before falling back to RAG) will query for the EXC/IDV class
of question. Still groundwork only: nothing in `routes.py`/`ollama_service.py`
reads from these tables yet, zero behavior change for the running chatbot.
`lab_api` rebuilt and restarted to apply the migration (same brief-restart
pattern as Phase 1).

## 2026-10-15 — Phase 1 of the clean-schema project: shared code glossary tables

**Files:** `backend/alembic/versions/20261015_01_code_glossary_tables.py`,
`backend/app/models.py`, `backend/scripts/seed_code_glossary.py`,
`excel-sources/SHEET_MAP.md`, `excel-sources/CODE_GLOSSARY.md`

Follow-up to the 2026-10-14 KB audit, which found the DOCX content faithful to
the real Excel but also found that the Excel itself has a layer of structure
the DOCX conversion never captured: codes (DMS, TKO, EXC, IDV, zone codes,
network-segment codes...) that are reused across multiple sheets and articles
by convention, not by any formula, and are currently redefined independently
wherever they're used instead of having one canonical source.

Added 5 new tables — `closure_codes`, `network_segments`, `zones`, `regions`,
`activite_codes` — and seeded them from the audit, with every row's
`source_notes` citing the exact sheet or screenshot it came from, and a
`confidence` flag (`confirmed_by_text` vs `context_only`) so a code seen only
in usage context is never presented as if its meaning were confirmed.

`activite_codes` uses a `(code, perimeter)` composite key rather than `code`
alone, because `IDV` is confirmed to be two different codes: a Cuivre
activité (`GEM-CUIVRE-010`, Production) and, separately, an FTTH activité
(the GEM-eligibility matrix found in `Expertise & Fiabilisation`'s
screenshots, Production/BtB). `EXC` is FTTH-only (Maintenance/Hors BtB) —
the same matrix makes explicit, in the source material itself, exactly the
distinction the EXC/IDV pilot bug was missing.

This is pure groundwork: the tables are live in Postgres (migration applied,
`lab_api` rebuilt and restarted to pick up the new models) but nothing in the
chat/retrieval pipeline reads from them yet — zero behavior change for the
running chatbot. 22 closure codes, 25 network segments, 12 zones, 8 regions,
43 activité codes seeded (9/22 closure codes and all 43 activité codes have a
confirmed textual definition; the rest are flagged `context_only` pending a
clearer source). Next: Phase 2 — decision tables for the ~19-23 lookup-style
KB articles, populated directly from the Excel workbook.

## 2026-10-13 — Retrieval itself now finds the right code instead of just refusing when it can't

**Files:** `backend/app/services/retrieval_service.py`, `backend/tests/test_phase4b_performance.py`

Follow-up to the exact-code guard added earlier today. That guard stops the
chatbot from *answering wrong* when the asked-about code isn't in what got
retrieved, but it doesn't fix retrieval itself — it was still a coin flip
whether the right source got surfaced at all. The real EXC/IDV case showed
why: `_lexical_rerank_score()` already had an "exact operational identifier"
bonus (`+4.0` for PM/PB/F04-style acronyms) specifically for this kind of
mixup, but it was too small to matter. Computed by hand against the actual
retrieved chunks: the wrong IDV row scored ~14-16 purely from generic
phrase/token overlap ("sans RDV", "échec = ABS" are common to hundreds of
rows), while a chunk that actually defines EXC scored ~6 — the +4 bonus for
having the right code couldn't close that gap, let alone overcome chunks
that don't have it at all.

Changed section 3 of `_lexical_rerank_score` from a one-sided bonus to a
symmetric ±20-per-code adjustment: a chunk containing every code token the
question explicitly named (agents write these in caps) gets a large boost;
a chunk missing even one gets an equally large penalty. Only engages when
the question actually names a code (`_query_acronyms()` non-empty) — a
plain-language question is scored exactly as before.

Verified against the real, live corpus (not a mock): `search_chunks("comment
cloturer EXC sans rdv en abs")` now returns 5/5 chunks that actually mention
EXC (including "Si le dossier est EXC, alors aucun gardé en main n'est
autorisé" and confirmation EXC requires an appointment) — zero mention of
IDV, where before this exact query was what produced the wrong answer. Also
checked a normal in-table case (activité R02, échec ABS, canal retails)
still ranks its own correct row #1, correctly above the near-identical
Wholesale variant of the same row — and a plain question with no code in it
is retrieved identically to before. Added 2 new tests reproducing the
EXC/IDV scoring gap directly (confirms the wrong row's score actually goes
negative, and the EXC-defining chunk now outranks it) alongside the existing
PB/PM acronym-discrimination tests, which still pass unchanged. Full suite:
297 backend tests, same 4 pre-existing unrelated failures as always, no
regressions. Image rebuilt, only `lab_api` recreated.

With retrieval now actually finding the right source in this case, the
guard rail from earlier today stays dormant for it (EXC is present, so
generation proceeds normally) — it remains the safety net for cases where
a code genuinely isn't documented anywhere in the KB.

## 2026-10-13 — Chatbot substituted a different code's row when the exact one it was asked about wasn't in the sources

**Files:** `backend/app/services/ollama_service.py`, `backend/app/routes.py`,
`backend/tests/test_chat.py`, `backend/tests/test_phase4b_performance.py`

User reported, with a real pilot example: asked *"comment clôturer EXC sans
rdv en abs"*; the chatbot answered "pour une activité IDV et un échec ABS, le
code clôture/situation est RMC..." — a completely different activity code
(IDV) than the one asked about (EXC). Traced it to the actual retrieved
chunk: `GEM-CUIVRE-010` is a 176-row reference table (23 activity codes × 4
failure types × 2 channels) converted into ~186 near-identical templated
"rule" chunks, one per row, differing only by a couple of short category
codes. EXC isn't even one of that table's 23 codes — it's a different
activity defined in a separate article — but a row for "IDV" scored as
semantically close (shared phrasing like "sans RDV") and got retrieved and
answered from anyway. Same root cause affects at least 8 other KB articles
built from similar lookup tables (~500 near-duplicate row-chunks total) —
likely the bulk of real FDE "quel code pour quelle situation" questions.
Retrieval confidence looked fine throughout (topically close, decent
cosine score) because the failure is about *entity* correctness, not topic
relevance — exactly why the existing confidence metrics didn't catch it.

A prompt-level safeguard for this already existed (`retrieval_safety_block`
in `build_grounded_prompt`), but only activated for questions literally
containing "quel code" or "code de clôture" — "comment clôturer" didn't
match, and a prompt instruction alone isn't a hard guarantee with a local
model anyway.

Added a deterministic guard instead of relying on the model to follow
instructions: `_question_code_tokens()` extracts short all-caps tokens from
the raw question (agents write these codes in caps, same as the source
tables); `_missing_question_codes()` checks whether each one actually
appears in the chunks about to be handed to the model. If a code the agent
explicitly typed is missing from every retrieved chunk, both
`generate_answer_with_ollama()` and `stream_answer_with_ollama()` skip
calling Ollama entirely and return a fixed "not found for this exact code"
message instead — the model never gets a chance to substitute a different
row. The response's reported confidence is forced to `"low"` in that case,
so it flows into the existing knowledge-gap tracking automatically.

Known limitation of this fast version: it only catches codes spelled in
caps in the question (as agents do here); a lowercase-typed code slips
through. A more thorough fix (keyword/exact-match retrieval for these ~9
lookup-table articles) was discussed and deferred — this guard addresses
the reported case now without changing the retrieval architecture.

Verified: 7 new tests reproducing the exact EXC/IDV case — unit tests for
the token extraction and mismatch detection, both generation functions
confirmed to never call Ollama's HTTP session when triggered, and a full
`/api/v1/chat` integration test confirming the response comes back with
`confidence: "low"` and `generation_provider: "exact_code_guard"`. Full
suite: 295 backend tests, same 4 pre-existing unrelated failures as
always, no regressions. Image rebuilt, only `lab_api` recreated.

## 2026-10-12 — Auto-refresh the knowledge-gap panel while the pilot is live

**Files:** `backend/frontend/src/features/admin/KnowledgeGapPanel.tsx`,
`backend/frontend/tests/knowledgeGapAutoRefresh.test.ts`

Requested to monitor what the pilot agents are asking as it happens,
without manually reloading the panel. Added a 20s polling interval that
re-fetches the list in the background, paused automatically while the
detail dialog is open (so it can't yank away the current item mid-review
or mid-resolution-note-editing) and without flipping the full-page
loading/error state on each poll — only an explicit action (changing the
status filter, paging, resolving an item) does that; a background poll
silently updates the table or, on failure, does nothing and tries again
on the next tick. A small label next to the question count shows whether
auto-refresh is currently active or paused.

Verified: 3 new source-pattern tests (no component-rendering harness in
this suite, same approach as `sessionExpiry.test.ts`), full suite (57
frontend tests), lint and build clean. Frontend rebuilt and redeployed;
confirmed the served bundle hash matches the new build.

## 2026-10-12 — CORS still broke on a second pilot laptop using a different tunnel port

**File:** `backend/app/main.py`

A previous fix (2026-09-17 entry below) widened CORS to also accept the app's
deployed origins `http://localhost` and `http://127.0.0.1` (port 80, no
explicit port), on top of the Vite dev ports. That covered my own laptop,
whose SSH tunnel happens to forward port 80 straight through. Testing from a
second laptop (different OS user, same VM) with `ssh -L 8080:localhost:80`
exposed the real shape of the bug: each pilot agent's tunnel will land on
whatever local port happens to be free on their machine, and the allow-list
was still a fixed set of exact origins — so `http://localhost:8080` was
blocked by the browser before any request reached the backend. Confirmed via
the browser console showing a CORS error, and reproduced with a raw `curl`
`OPTIONS` preflight carrying `Origin: http://localhost:8080`.

Replaced the exact-origin list with `allow_origin_regex=r"^http://(localhost|
127\.0\.0\.1)(:\d+)?$"`, accepting any port on `localhost`/`127.0.0.1` while
still rejecting everything else. Verified live: a preflight with
`Origin: http://localhost:8080` now gets `access-control-allow-origin:
http://localhost:8080` back; one with `Origin: http://evil.com` gets no
CORS headers at all.

Verified: full backend suite (288 tests, same 4 pre-existing unrelated
failures as always), image rebuilt, only `lab_api` recreated.

## 2026-10-12 — Agent's feedback reason/comment weren't visible in the admin panel

**Files:** `backend/alembic/versions/20261012_01_knowledge_gap_feedback_detail.py`,
`backend/app/models.py`, `backend/app/services/knowledge_gap_service.py`,
`backend/app/feedback_routes.py`, `backend/app/admin_schemas.py`,
`backend/tests/test_feedback_workflow.py`,
`backend/frontend/src/features/admin/KnowledgeGapPanel.tsx`,
`backend/frontend/src/types/admin.ts`

User caught a real gap, verified by reading the code: when an agent's
feedback (👎/partially-helpful) bridges into the knowledge-gaps panel,
`flag_knowledge_gap_from_feedback()` only ever copied the boolean signal
over — the actual reason selected from the dropdown and the agent's free-text
comment stayed in `message_feedback`, never reaching the panel. Someone
reviewing it saw "an agent flagged this" with no idea why.

Added three columns (`user_feedback_rating`, `user_feedback_reason`,
`user_feedback_comment`) to `knowledge_gaps`, populated on both paths —
creating a new gap from feedback, and marking an existing automatic gap —
so the detail isn't lost either way. Displayed in the panel's detail
dialog, translated to the same French labels already used in the chat's
own feedback dropdown, so the wording matches what the agent actually saw.

Backfilled the 7 pre-existing flagged entries from their original
`message_feedback` rows, so this isn't just fixed for future feedback —
confirmed live via the real admin API that historical entries now show
their real reason/comment (e.g. gap 43: "incomplete_answer" / "manque une
partie de la réponse").

Verified: full suite (288 backend, same 4 pre-existing unrelated failures
confirmed before this change; 54 frontend), build+lint clean, migration
applied, image rebuilt/restarted, confirmed live end-to-end through the
real admin API before and after the backfill.

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
