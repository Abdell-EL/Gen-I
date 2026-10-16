"""Deterministic answers read straight from `decision_table_rows` (Phase 2 of
the clean-schema project) instead of embeddings + reranking.

Two tiers:

1. The GEM-eligibility tables (Cuivre and FTTH) get bespoke logic, because
   they need canal/perimeter disambiguation -- this is exactly what the
   EXC/IDV pilot bug was about: `IDV` exists as two unrelated codes (Cuivre
   and FTTH), and this module resolves the ambiguity from an explicit signal
   in the question rather than from embedding similarity.
2. Every other decision table (22 of them: Setting Echecs, Alea Normés, the
   flat closure-code tables, Gestar, Lot et Chantier, the activité/produit
   glossaries...) goes through a generic matcher: every field in the table's
   key_schema must resolve to exactly one candidate value found in the
   question (an exact token match for short codes, an exact verbatim
   substring match for long free-text keys like a "cause" description or a
   PIDI error message), or the table is skipped.

In both tiers, anything that doesn't resolve fully -- an unrecognized code,
an ambiguous perimeter, more than one candidate for a field -- returns None
and the caller falls back to the existing retrieval+generation path
unchanged. This module never guesses.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.database import SessionLocal
from app.models import ActiviteCode, DecisionTable, DecisionTableLink, DecisionTableRow


def _fold_accents(text: str) -> str:
    """Strip accents for comparison only (never for display): long French
    phrase keys ("inférieur", "Défaut", "Affectés"...) shouldn't require a
    typed question to hit every accent exactly -- many people type fast
    without them. Short codes don't need this; they're already ASCII."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )

_GEM_CUIVRE_TABLE_NAME = "GEM Cuivre - Eligibilité AB/RF/TVC/MC"
_GEM_FTTH_TABLE_NAME = "GEM FTTH - Eligibilité AB/RF/MC/TC"

_CUIVRE_SIGNAL_RE = re.compile(r"\bcuivre\b", re.IGNORECASE)
_FTTH_SIGNAL_RE = re.compile(r"\b(ftth|fibre|fth)\b", re.IGNORECASE)
_WHOLESALE_RE = re.compile(r"\bwholesale\b", re.IGNORECASE)
_RETAIL_RE = re.compile(r"\bretails?\b", re.IGNORECASE)

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-]{1,10}")


def _candidate_tokens(question: str) -> set[str]:
    words = _TOKEN_RE.findall(question)
    tokens = {w.upper() for w in words}
    # multi-word activité codes exist (e.g. "DET MT")
    for i in range(len(words) - 1):
        tokens.add(f"{words[i].upper()} {words[i + 1].upper()}")
    return tokens


def _find_activite_matches(db, question: str) -> list[ActiviteCode]:
    tokens = _candidate_tokens(question)
    if not tokens:
        return []
    return db.query(ActiviteCode).filter(ActiviteCode.code.in_(tokens)).all()


def _resolve_perimeter(question: str, perimeters: set[str]) -> str | None:
    if len(perimeters) == 1:
        return next(iter(perimeters))
    if _CUIVRE_SIGNAL_RE.search(question) and "Cuivre" in perimeters:
        return "Cuivre"
    if _FTTH_SIGNAL_RE.search(question) and "FTTH" in perimeters:
        return "FTTH"
    return None


def _table_rows(db, table_name: str) -> tuple[DecisionTable | None, list[DecisionTableRow]]:
    table = db.query(DecisionTable).filter_by(name=table_name).one_or_none()
    if table is None:
        return None, []
    rows = db.query(DecisionTableRow).filter_by(table_id=table.table_id).all()
    return table, rows


def _find_echec(question: str, echec_options: set[str]) -> str | None:
    upper = question.upper()
    for echec in sorted(echec_options, key=len, reverse=True):
        if re.search(rf"\b{re.escape(echec.strip())}\b", upper):
            return echec
    return None


def _linked_table_hints(db, table: DecisionTable, rows: list[DecisionTableRow]) -> list[str]:
    """The decision tables are not independent -- some rows' own text points
    at another table ("voir consigne de reprise de rdv", "voir Aléa Normés").
    Surface that explicitly instead of leaving it buried in the raw text,
    using the links catalogued in decision_table_links (2026-10-15 remap).
    """
    links = db.query(DecisionTableLink).filter_by(source_table_id=table.table_id).all()
    if not links:
        return []
    row_text = " ".join(
        str(v) for row in rows for v in row.value_columns.values() if isinstance(v, str)
    ).lower()
    hints = []
    for link in links:
        pattern = (link.source_text_pattern or "").lower()
        if pattern and pattern in row_text:
            target = db.get(DecisionTable, link.target_table_id)
            if target:
                hints.append(f"→ Voir aussi : « {target.name} » ({link.trigger_description})")
    return hints


def _format_cuivre_answer(
    activite: str, echec: str, rows: list[DecisionTableRow], hints: list[str],
) -> str:
    lines = [f"Pour l'activité Cuivre « {activite} », échec « {echec} » :"]
    for row in sorted(rows, key=lambda r: str(r.key_columns.get("canal") or "")):
        v = row.value_columns
        canal = (row.key_columns.get("canal") or "").strip()
        lines.append(
            f"- Canal {canal} : code clôture/situation « {v.get('code_cloture_situation') or 'non applicable'} », "
            f"durée GEM « {v.get('duree_gem') or 'non précisée'} », "
            f"aléa normé « {v.get('alea_normes') or 'non précisé'} ». "
            f"IDF : {v.get('idf') or 'non précisé'}."
        )
    lines.extend(hints)
    return "\n".join(lines)


def _lookup_gem_cuivre(db, question: str, activite: str) -> dict[str, Any] | None:
    table, rows = _table_rows(db, _GEM_CUIVRE_TABLE_NAME)
    if table is None or not rows:
        return None
    echec_options = {r.key_columns.get("echec") for r in rows if r.key_columns.get("echec")}
    echec = _find_echec(question, echec_options)
    if echec is None:
        return None
    matching = [r for r in rows if r.key_columns.get("activite") == activite and r.key_columns.get("echec") == echec]
    if not matching:
        return None
    if _WHOLESALE_RE.search(question):
        matching = [r for r in matching if "wholesale" in (r.key_columns.get("canal") or "").lower()]
    elif _RETAIL_RE.search(question):
        matching = [r for r in matching if "retail" in (r.key_columns.get("canal") or "").lower()]
    if not matching:
        return None
    hints = _linked_table_hints(db, table, matching)
    return {
        "answer": _format_cuivre_answer(activite, echec, matching, hints),
        "source_table": _GEM_CUIVRE_TABLE_NAME,
        "matched_rows": len(matching),
    }


def _format_ftth_answer(
    activite: str, echec: str, row: DecisionTableRow, hints: list[str],
) -> str:
    v = row.value_columns
    parts = [
        f"Pour l'activité FTTH « {activite} », échec « {echec} » : "
        f"durée GEM « {v.get('duree_gem') or 'non précisée'} », "
        f"code clôture/situation « {v.get('code_cloture_situation') or 'non applicable'} », "
        f"aléa normé « {v.get('alea_normes') or 'non précisé'} »."
    ]
    if v.get("commentaire"):
        parts.append(f"Commentaire : {v['commentaire']}.")
    text = " ".join(parts)
    if hints:
        text += "\n" + "\n".join(hints)
    return text


def _lookup_gem_ftth(db, question: str, activite: str) -> dict[str, Any] | None:
    table, rows = _table_rows(db, _GEM_FTTH_TABLE_NAME)
    if table is None or not rows:
        return None
    echec_options = {r.key_columns.get("echec") for r in rows if r.key_columns.get("echec")}
    echec = _find_echec(question, echec_options)
    if echec is None:
        return None
    matching = [r for r in rows if r.key_columns.get("activite") == activite and r.key_columns.get("echec") == echec]
    if len(matching) != 1:
        return None
    hints = _linked_table_hints(db, table, matching)
    return {
        "answer": _format_ftth_answer(activite, echec, matching[0], hints),
        "source_table": _GEM_FTTH_TABLE_NAME,
        "matched_rows": 1,
    }


_SAV_FIABILISATION_MATRIX_TABLE_NAME = (
    "FTTH SAV+ - Éligibilité GEM par activité (Production/Maintenance, BtB/Hors BtB)"
)
_EXPERTISE_ALEA_DUREE_TABLE_NAME = (
    "Expertise & Fiabilisation - Durée aléa GEM standard par activité (AB/RF/TC/MC/BL)"
)


def _sav_fiabilisation_conflict_note(db, activite: str, v: dict) -> str | None:
    """`FTTH SAV+ - Éligibilité GEM par activité` (a hand-transcribed
    screenshot) and `Expertise & Fiabilisation - Durée aléa GEM standard...`
    (real cells, same source sheet, a different image) can disagree for the
    same activité -- confirmed for EXC during the 2026-10-15 remap, after
    ruling out every non-conflict explanation found (image proximity, hidden
    columns, cell comments, colour-coding). Per explicit instruction: don't
    pick a winner silently -- surface both values so the conflict is visible
    instead of hidden behind whichever table happened to answer first.
    """
    _, duree_rows = _table_rows(db, _EXPERTISE_ALEA_DUREE_TABLE_NAME)
    activite_rows = [r for r in duree_rows if r.key_columns.get("activite") == activite]
    if not activite_rows:
        return None
    values = {(r.value_columns.get("gem_autorise") or "").strip().upper() for r in activite_rows}
    if values != {"NON"}:
        return None  # only flag the proven case: that table says NON across every échec
    matrix_says_oui = (v.get("gem_autorise_btb") or "").strip().lower() == "oui" or (
        v.get("gem_autorise_hors_btb") or ""
    ).strip().lower() == "oui"
    if not matrix_says_oui:
        return None
    echecs = ", ".join(sorted(r.key_columns.get("echec", "") for r in activite_rows))
    return (
        f"⚠ Conflit de sources non résolu : « {_EXPERTISE_ALEA_DUREE_TABLE_NAME} » "
        f"dit GEM NON pour « {activite} » quel que soit l'échec ({echecs}), ce qui "
        f"contredit la ligne ci-dessus. Vérifié en détail (feuille Excel "
        f"« Expertise & Fiabilisation », lignes 67-73 vs capture d'écran du même "
        f"onglet) sans trouver d'explication qui lève la contradiction -- à "
        f"confirmer avec le métier avant de traiter un cas contesté."
    )


def _lookup_sav_fiabilisation_matrix(db, activite: str) -> dict[str, Any] | None:
    table, rows = _table_rows(db, _SAV_FIABILISATION_MATRIX_TABLE_NAME)
    if table is None or not rows:
        return None
    matching = [r for r in rows if r.key_columns.get("activite") == activite]
    if len(matching) != 1:
        return None
    v = matching[0].value_columns
    answer = (
        f"Pour l'activité FTTH « {activite} » ({v.get('perimetre') or 'périmètre non précisé'}) : "
        f"GEM autorisé en BtB = « {v.get('gem_autorise_btb') or 'non précisé'} », "
        f"GEM autorisé Hors BtB = « {v.get('gem_autorise_hors_btb') or 'non précisé'} »."
        + (f" ({v['note']})" if v.get("note") else "")
    )
    conflict = _sav_fiabilisation_conflict_note(db, activite, v)
    if conflict:
        answer += "\n" + conflict
    return {"answer": answer, "source_table": _SAV_FIABILISATION_MATRIX_TABLE_NAME, "matched_rows": 1}


def _find_gem_answer(db, question: str) -> dict[str, Any] | None:
    matches = _find_activite_matches(db, question)
    if not matches:
        return None
    codes = {m.code for m in matches}
    if len(codes) != 1:
        return None  # more than one distinct activité code named -- ambiguous
    activite = next(iter(codes))
    perimeters = {m.perimeter for m in matches}
    perimeter = _resolve_perimeter(question, perimeters)
    if perimeter is None:
        return None
    if perimeter == "Cuivre":
        return _lookup_gem_cuivre(db, question, activite)
    if perimeter == "FTTH":
        # Two independent FTTH sources can answer an activité question: the
        # échec-keyed Setting Fibre table (needs an échec named) and the
        # SAV+ matrix (activité alone, no échec -- this is EXC's only source,
        # since EXC was never a row in Setting Fibre at all). Try the more
        # specific one first; it declining isn't the same as a conflict, so
        # fall through rather than treating "zero echec matches" as ambiguous.
        answer = _lookup_gem_ftth(db, question, activite)
        if answer is not None:
            return answer
        return _lookup_sav_fiabilisation_matrix(db, activite)
    return None


# --- Generic lookup for the remaining decision tables -----------------------
#
# The GEM tables above get bespoke logic because they need canal/perimeter
# disambiguation. Everything else is either a short-code key (an échec,
# région, zone, activité code -- same safe exact-token-match as GEM) or a
# long free-text key (a "cause" or "cas rencontré" description, a PIDI error
# message...). For the latter, exact-token matching doesn't apply -- instead
# the full phrase must appear verbatim in the question. That's strict (these
# will rarely fire for long-text keys unless someone pastes the exact wording)
# but it's the honest tradeoff: a loose/fuzzy match on free text is exactly
# the embedding-similarity problem this whole project exists to avoid.
#
# Every key field in a table's key_schema must resolve to exactly one
# candidate, or the table is skipped entirely -- no partial matches.

# Two tiers, not a flat list. Tier 1 is the operational/clôture-decision
# tables -- this is where the proven, high-value pilot questions live (GEM
# eligibility, échecs, consignes...). Tier 2 is only consulted when NOTHING
# in tier 1 resolves: broad code->description glossaries and the Facturation
# tables, whose "activité" keys are the single most collision-prone kind
# (short codes that also appear, meaning something different, in several
# tier-1 tables). Without this split, adding Facturation broke the flagship
# EXC/IDV pilot case: "comment clôturer EXC..." started colliding between the
# GEM-eligibility answer (what the question is actually about) and the
# billing-article answer for the same bare code "EXC" -- tiering restores
# tier 1's priority instead of treating that as symmetric ambiguity.
# The SAV+ matrix is NOT in this list -- it has the same Cuivre/FTTH
# perimeter-collision risk as the two bespoke GEM tables (e.g. "MIT" and
# "IDV" both exist, meaning something different, in Cuivre and FTTH), so it's
# handled by `_find_gem_answer` above instead, which already knows how to
# decline on that ambiguity. A generic table has no such awareness.
_TIER_1_OPERATIONAL_TABLES = [
    "RDV - Consignes de reprise/réinjection par techno et région",
    "FDE - Référentiel des échecs (Setting Echecs)",
    "FDE - Aléas normés (Setting Alea 2)",
    "SAV Fibre - Typologie vers code de clôture",
    "SAV+ Fiabilisation - Cas vers code responsabilité/relève",
    "FTTH SAV+ - Levier Wholesale (ligne LBE vs non-LBE)",
    "SAV+ Expertise - Cas vers consigne",
    "FDE VE - Code VE par activité/produit",
    "FDE VE - Code par typologie échec",
    "FDE - Erreurs de transfert PIDI (flèche rouge)",
    "FTTH Accès/Service - Codes de clôture",
    "FTTH Production Hors IHX LMX - Codes de clôture",
    "Cuivre Accès/Service - Codes de clôture",
    "SAV FTTH - Codes de clôture",
    "RF Soir - Traitement selon état, date d'affectation et RDV",
    "F04/P03 - Codes de clôture et messages client",
    "SBL - Cas rencontré vers action GESICA",
    "GESTAR - Codes de relève vers article de facturation",
    "FDE - Tickets à utiliser selon le contexte",
    "FDE - Situations justifiant une mise en Réaffecté BL",
    "Lot et Chantier Cuivre",
    "Lot et Chantier FTTH",
]

# Tier 2: Facturation. Still collision-prone (short activité keys) but more
# specific/valuable than a bare code->description lookup, so it goes before
# tier 3, not alongside it -- "quel article pour R02 hors REH" is a specific,
# answerable question that a bare "R02" glossary match shouldn't be allowed
# to block just by coincidentally matching the same question.
_TIER_2_FACTURATION_TABLES = [
    "Facturation Cuivre - Activité vers article de facturation",
    "Facturation Cuivre - Matrice activité x code de facturation",
    "Facturation FTTH - Matrice activité x code de facturation",
]

# Tier 3: last resort. A bare activité/produit code is the single most
# collision-prone kind of key in this whole system (shortest, least context),
# so these glossaries only get consulted once every more specific tier above
# has found nothing at all.
_TIER_3_GLOSSARY_TABLES = [
    "Activités Production Cuivre",
    "Produits Cuivre",
    "Activités Production FTTH",
    "Produits FTTH",
]


def _match_field(question: str, candidates: set[Any]) -> Any | None:
    # A few key fields (billing codes like 2418, 6310) are stored as numbers,
    # not strings -- match on the string form but return the original value,
    # since that's what has to compare equal to row.key_columns later.
    #
    # The split that matters is "multi-word phrase" vs "single token", not
    # raw length: a short-but-multi-word code like "R02 hors REH" (12 chars,
    # 3 words) needs the same verbatim-substring treatment as a long "cause"
    # description, since exact single-token matching can never find it (no
    # trigram generation) and a length cutoff alone put it in neither tier.
    by_text = {str(c).strip(): c for c in candidates if c is not None and str(c).strip()}
    if not by_text:
        return None
    folded_tokens = {_fold_accents(t) for t in _candidate_tokens(question)}
    folded_question = _fold_accents(question.lower())
    matches = set()
    for text, orig in by_text.items():
        if " " in text:
            if _fold_accents(text.lower()) in folded_question:
                matches.add(orig)
        elif _fold_accents(text.upper()) in folded_tokens:
            matches.add(orig)
    if len(matches) == 1:
        return next(iter(matches))
    return None  # zero or multiple candidates matched this field -- no guess


def _format_generic_answer(
    table_name: str,
    resolved_key: dict[str, str],
    value_schema: list[str],
    rows: list[DecisionTableRow],
    hints: list[str] | None = None,
) -> str:
    key_desc = ", ".join(f"{field.replace('_', ' ')} = « {val} »" for field, val in resolved_key.items())
    if not value_schema:
        text = f"D'après « {table_name} », {key_desc} est un cas reconnu dans la source."
        return text + ("\n" + "\n".join(hints) if hints else "")

    def _row_text(row: DecisionTableRow) -> str:
        v = row.value_columns
        parts = []
        for field in value_schema:
            val = v.get(field)
            if not val:
                continue
            if isinstance(val, dict):
                sub = "; ".join(f"{sk} : {sv}" for sk, sv in val.items() if sv)
                if sub:
                    parts.append(f"{field.replace('_', ' ')} ({sub})")
            else:
                parts.append(f"{field.replace('_', ' ')} : {val}")
        return " ; ".join(parts) if parts else "aucune valeur renseignée"

    if len(rows) == 1:
        text = f"D'après « {table_name} », pour {key_desc} : {_row_text(rows[0])}."
    else:
        lines = [f"D'après « {table_name} », pour {key_desc} :"]
        lines.extend(f"- {_row_text(row)}" for row in rows)
        text = "\n".join(lines)
    if hints:
        text += "\n" + "\n".join(hints)
    return text


def _generic_table_lookup(db, table_name: str, question: str) -> dict[str, Any] | None:
    table, rows = _table_rows(db, table_name)
    if table is None or not rows:
        return None
    key_schema = table.key_schema or []
    if not key_schema:
        return None

    resolved: dict[str, str] = {}
    for field in key_schema:
        candidates = {r.key_columns.get(field) for r in rows if r.key_columns.get(field)}
        if not candidates:
            continue  # field never populated in this table -- not part of the real key
        match = _match_field(question, candidates)
        if match is None:
            return None
        resolved[field] = match
    if not resolved:
        return None

    matching = [r for r in rows if all(r.key_columns.get(f) == v for f, v in resolved.items())]
    if not matching:
        return None

    hints = _linked_table_hints(db, table, matching)
    return {
        "answer": _format_generic_answer(table.name, resolved, table.value_schema or [], matching, hints),
        "source_table": table.name,
        "matched_rows": len(matching),
    }


def _first_unambiguous_match(db, question: str, table_names: list[str]) -> dict[str, Any] | None:
    # Collect every table in this tier that resolves, rather than returning
    # the first by priority order. A bare code like "IDV" with no other
    # signal is exactly what the GEM tables correctly decline to answer
    # (ambiguous perimeter) -- a code-keyed table doesn't know about that
    # ambiguity on its own, so if more than one table in the SAME tier
    # resolves, that's a conflict to decline, not a priority to break by
    # picking whichever table happens to come first.
    matches = [
        answer
        for name in table_names
        if (answer := _generic_table_lookup(db, name, question)) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def find_decision_table_answer(question: str) -> dict[str, Any] | None:
    """Return a deterministic answer from any decision table, or None to fall
    back to RAG.

    Never guesses: an unresolvable or ambiguous key field returns None rather
    than picking a plausible-looking answer. Four tiers, each tried only if
    the previous one found nothing: (1) the GEM eligibility tables, bespoke
    Cuivre/FTTH perimeter handling, including the SAV+ matrix as an FTTH
    fallback when no échec is named; (2) the other operational/clôture tables;
    (3) Facturation; (4) the bare code->description glossaries, last because
    a short activité code is the most collision-prone kind of key, and the
    operational "what do I do" answers matter more for a pilot agent than
    "what article do I bill" or "what does this code mean" when a question
    could plausibly be about any of them.
    """
    db = SessionLocal()
    try:
        gem_answer = _find_gem_answer(db, question)
        if gem_answer is not None:
            return gem_answer

        tier1 = _first_unambiguous_match(db, question, _TIER_1_OPERATIONAL_TABLES)
        if tier1 is not None:
            return tier1

        tier2 = _first_unambiguous_match(db, question, _TIER_2_FACTURATION_TABLES)
        if tier2 is not None:
            return tier2

        return _first_unambiguous_match(db, question, _TIER_3_GLOSSARY_TABLES)
    finally:
        db.close()
