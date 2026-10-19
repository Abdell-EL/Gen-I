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
# PID error codes (e.g. "PID-1205.2") don't tokenize under _TOKEN_RE -- the
# decimal point splits them into two tokens, neither of which is the actual
# code. Not worth widening _TOKEN_RE itself (shared by every table's
# matching, and "." in a general-purpose token class risks swallowing
# trailing sentence punctuation elsewhere) -- narrow, additive extraction
# for this one known domain pattern instead. Found 2026-10-16 fixing the
# PIDI errors table to match on its own short code.
_PID_CODE_RE = re.compile(r"PID-?(\d+(?:\.\d+)?)", re.IGNORECASE)


def _candidate_tokens(question: str) -> set[str]:
    words = _TOKEN_RE.findall(question)
    tokens = {w.upper() for w in words}
    # multi-word activité codes exist (e.g. "DET MT")
    for i in range(len(words) - 1):
        tokens.add(f"{words[i].upper()} {words[i + 1].upper()}")
    for m in _PID_CODE_RE.finditer(question):
        tokens.add(f"PID-{m.group(1)}")
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
_FACT_CUIVRE_ARTICLE_TABLE = "Facturation Cuivre - Activité vers article de facturation"
_FACT_CUIVRE_MATRIX_TABLE = "Facturation Cuivre - Matrice activité x code de facturation"
_FACT_FTTH_MATRIX_TABLE = "Facturation FTTH - Matrice activité x code de facturation"

# Billing an activité also needs its Lot/Chantier routing code, which lives
# in a completely separate table keyed by zone + activité ("Lot et Chantier
# Cuivre"/"...FTTH") -- a bare activité question has no zone in it, so this
# can't be resolved and merged automatically without guessing the zone.
# Surfacing it explicitly instead of silently leaving the ticket half-routed.
_FACTURATION_LOT_CHANTIER_NOTE = (
    "ℹ️ Pour router ce dossier il faut aussi le Lot et le Chantier, qui dépendent de la zone "
    "(« Lot et Chantier Cuivre »/« ...FTTH », clé zone + activité) -- précisez la zone si besoin."
)


def _lookup_facturation_cuivre_merged(db, question: str) -> dict[str, Any] | None:
    """`Facturation Cuivre` is one sheet with two parallel views of the same
    billing process: a clean "Activité -> Article" list (cols AB:AD) and a
    checkbox matrix (cols G:Z) -- found 2026-10-16 the same way the SAV+
    sheet's "Fiabilisation"/"Expertise" split was found: by tracing a real
    regression ("MIT" stopped answering) back to its cause. For most
    activités the matrix has several candidate rows (genuinely ambiguous on
    its own, correctly left alone -- not touched here) but for a few it has
    exactly one, and that one legitimately matching table was making the
    *other*, already-correct table's answer get silently declined by the
    tier's "two tables resolved = ambiguous" safety rule -- even though both
    tables were describing the same fact, not competing for different ones.
    Only intervenes in that narrow, provably-safe case: combines the two
    into one answer when they agree, and surfaces an explicit conflict note
    (same pattern as the EXC GEM-eligibility flag) if they don't.
    """
    table, rows = _table_rows(db, _FACT_CUIVRE_ARTICLE_TABLE)
    if table is None or not rows:
        return None
    candidates = {r.key_columns.get("activite") for r in rows if r.key_columns.get("activite")}
    activite = _match_field(question, candidates)
    if activite is None:
        return None
    matching = [r for r in rows if r.key_columns.get("activite") == activite]
    if len(matching) != 1:
        return None
    article_row = matching[0].value_columns

    _, matrix_rows = _table_rows(db, _FACT_CUIVRE_MATRIX_TABLE)
    matrix_matches = [r for r in matrix_rows if r.key_columns.get("activite") == activite]

    lines = [
        f"D'après « {_FACT_CUIVRE_ARTICLE_TABLE} », pour activité « {activite} » : "
        f"code clôture « {article_row.get('code_cloture') or 'non précisé'} », "
        f"article « {article_row.get('article') or 'non précisé'} »."
    ]
    if len(matrix_matches) == 1:
        mv = matrix_matches[0].value_columns
        matrix_code = matrix_matches[0].key_columns.get("code_facturation")
        same = str(matrix_code).strip().upper() in str(article_row.get("article") or "").strip().upper()
        if same:
            lines.append(
                f"Confirmé par « {_FACT_CUIVRE_MATRIX_TABLE} » : dossier « {mv.get('dossier_type') or 'non précisé'} », "
                f"groupe « {mv.get('groupe_complet') or 'non précisé'} »."
            )
        else:
            lines.append(
                f"⚠ Conflit de sources non résolu : « {_FACT_CUIVRE_MATRIX_TABLE} » donne le code de "
                f"facturation « {matrix_code} » pour cette activité, différent de l'article « "
                f"{article_row.get('article')} » ci-dessus -- à vérifier avant de facturer."
            )
    elif len(matrix_matches) > 1:
        codes = ", ".join(str(r.key_columns.get("code_facturation")) for r in matrix_matches)
        lines.append(
            f"« {_FACT_CUIVRE_MATRIX_TABLE} » a plusieurs codes possibles pour cette activité "
            f"({codes}) -- préciser le contexte pour les départager."
        )

    lines.append(_FACTURATION_LOT_CHANTIER_NOTE)
    return {
        "answer": "\n".join(lines),
        "source_table": _FACT_CUIVRE_ARTICLE_TABLE,
        "matched_rows": 1,
    }


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


_SAV_PLUS_PROCESS_NOTE = (
    "⚠ Cette réponse ne couvre qu'une partie du process SAV+ Fiabilisation/Expertise. "
    "Avant de clôturer, vérifiez aussi : (1) l'éligibilité GEM pour l'activité concernée "
    "(« FTTH SAV+ - Éligibilité GEM par activité » -- attention, en conflit connu pour EXC), "
    "et (2) si la ligne est LBE ou non-LBE (« FTTH SAV+ - Levier Wholesale »), qui décide si "
    "on reste en SAV Fiabilisation ou si on bascule en SAV Incident."
)
# Found 2026-10-16: a real test question about a "client Absent" case during
# Expertise got only the consigne from this table (correct, but incomplete)
# -- the actual question also needed GEM eligibility, which lives in a
# completely different table with no shared key to join on (these are
# parallel vocabularies for different phases of the same SAV+ process, not
# joinable rows -- confirmed by the sheet's own column headers "Fiabilisation"
# / "Expertises"). Can't assemble a single merged answer without a shared
# key, so instead: always surface the adjacent process pieces explicitly
# rather than silently answering only the one table that happened to match.
_SAV_PLUS_CLUSTER_TABLES = {
    "SAV Fibre - Typologie vers code de clôture",
    "SAV+ Fiabilisation - Cas vers code responsabilité/relève",
    "SAV+ Expertise - Cas vers consigne",
    "FTTH SAV+ - Levier Wholesale (ligne LBE vs non-LBE)",
}

# "SAV FTTH - Codes de clôture" gives a closure code for VB/VM (vandalisme)
# but has no field for the décharge-number requirement at all -- that fact
# lives in a *different* table ("FDE - Référentiel des échecs"), whose own
# régional consignes text says, verbatim, "Présence du numéro de décharge
# OBligatoire, si manque Décharge mettre le dossier en Réaffecté BL". Found
# 2026-10-16 chasing a real failed question ("PB vandalisé sans code de
# décharge, peut-on clôturer?") that landed on this table and got a closure
# code with no answer to the actual question asked. Not linked via
# decision_table_links because neither table's own text references the
# other -- this is two independently-sourced tables about the same real
# case, not one pointing at the other, so a static note citing the real
# source is the honest way to surface it instead of fabricating a "voir X".
_VANDALISME_DECHARGE_NOTE = (
    "⚠ Important : d'après « FDE - Référentiel des échecs » (même cas, PB/PM vandalisé), "
    "le numéro de décharge est OBLIGATOIRE pour clôturer. S'il manque, le dossier doit être "
    "mis en Réaffecté BL -- pas de clôture directe possible dans ce cas."
)


def _sav_ftth_cloture_hints(matching: list[DecisionTableRow]) -> list[str]:
    situations = {r.value_columns.get("code_situation") for r in matching}
    if situations & {"VB", "VM"}:
        return [_VANDALISME_DECHARGE_NOTE]
    return []


def _generic_table_lookup(
    db, table_name: str, question: str, allow_inference: bool = False,
) -> dict[str, Any] | None:
    table, rows = _table_rows(db, table_name)
    if table is None or not rows:
        return None
    key_schema = table.key_schema or []
    if not key_schema:
        return None

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for field in key_schema:
        candidates = {r.key_columns.get(field) for r in rows if r.key_columns.get(field)}
        if not candidates:
            continue  # field never populated in this table -- not part of the real key
        match = _match_field(question, candidates)
        if match is None:
            unresolved.append(field)
        else:
            resolved[field] = match
    if not resolved:
        return None
    if unresolved and not allow_inference:
        return None

    # A field with no textual signal in the question (e.g. nobody writes
    # "FTTH" when asking about a fibre-specific échec code like "VB") isn't
    # automatically a guess if the fields that DID match already force it to
    # one value -- found 2026-10-16 chasing a real failed question ("PB
    # vandalisé sans code de décharge") that had a correct, matchable
    # code_echec but no explicit "FTTH"/"Cuivre" token anywhere in it. This
    # never invents a value: it only accepts a field that's already the sole
    # remaining possibility among rows selected by real text matches: still
    # declines (no guess) the moment more than one value survives.
    if unresolved:
        narrowed = [r for r in rows if all(r.key_columns.get(f) == v for f, v in resolved.items())]
        for field in unresolved:
            values = {r.key_columns.get(field) for r in narrowed if r.key_columns.get(field)}
            if len(values) != 1:
                return None
            resolved[field] = next(iter(values))

    matching = [r for r in rows if all(r.key_columns.get(f) == v for f, v in resolved.items())]
    if not matching:
        return None

    hints = _linked_table_hints(db, table, matching)
    if table.name in _SAV_PLUS_CLUSTER_TABLES:
        hints = hints + [_SAV_PLUS_PROCESS_NOTE]
    if table.name == "SAV FTTH - Codes de clôture":
        hints = hints + _sav_ftth_cloture_hints(matching)
    if table.name in (_FACT_FTTH_MATRIX_TABLE, _FACT_CUIVRE_MATRIX_TABLE):
        hints = hints + [_FACTURATION_LOT_CHANTIER_NOTE]
    return {
        "answer": _format_generic_answer(table.name, resolved, table.value_schema or [], matching, hints),
        "source_table": table.name,
        "matched_rows": len(matching),
    }


def _first_unambiguous_match(
    db, question: str, table_names: list[str], allow_inference: bool = False,
) -> dict[str, Any] | None:
    # Collect every table in this tier that resolves, rather than returning
    # the first by priority order. A bare code like "IDV" with no other
    # signal is exactly what the GEM tables correctly decline to answer
    # (ambiguous perimeter) -- a code-keyed table doesn't know about that
    # ambiguity on its own, so if more than one table in the SAME tier
    # resolves, that's a conflict to decline, not a priority to break by
    # picking whichever table happens to come first.
    #
    # allow_inference is Tier-1-only (see find_decision_table_answer): the
    # field-backfill pass in _generic_table_lookup is safe on its own, but
    # Tier 2/3 are, by this file's own design, the most collision-prone
    # tables (short activité/produit codes shared across unrelated meanings)
    # -- letting a Tier-2 table resolve a field it previously left silent
    # measurably increased same-tier collisions there (found 2026-10-16: "MIT"
    # started colliding between two Facturation tables that both legitimately
    # matched once inference was unscoped). Keeping it off outside Tier 1
    # avoids trading real Tier-1 fixes for new Tier-2/3 ambiguity.
    matches = [
        answer
        for name in table_names
        if (answer := _generic_table_lookup(db, name, question, allow_inference)) is not None
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

        tier1 = _first_unambiguous_match(
            db, question, _TIER_1_OPERATIONAL_TABLES, allow_inference=True,
        )
        if tier1 is not None:
            return tier1

        fact_cuivre = _lookup_facturation_cuivre_merged(db, question)
        if fact_cuivre is not None:
            return fact_cuivre

        tier2 = _first_unambiguous_match(db, question, _TIER_2_FACTURATION_TABLES)
        if tier2 is not None:
            return tier2

        return _first_unambiguous_match(db, question, _TIER_3_GLOSSARY_TABLES)
    finally:
        db.close()
