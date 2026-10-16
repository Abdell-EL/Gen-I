"""Populate kb_articles -- the narrative-content half of the clean KB (Phase 5).

Source: data/processed/chunks.json, already verified against the real Excel
workbook/screenshots during the 2026-10-15 audit (see PROGRESS.md). Not a
blind copy: narrative_content is reconstructed from the chunk types that
actually carry facts (generic, key_points, business_case, rule) -- question/
faq chunks are skipped as redundant restatements of the same facts. The one
known error found in this content (IGB-TRT-004: "technicien DI" should be
"Technicien D3", confirmed against the real screenshot) is corrected here.

Run inside the api container:
  docker exec -w /app -e PYTHONPATH=/app lab_api python scripts/populate_kb_articles.py
"""
from __future__ import annotations

import json

from app.database import SessionLocal
from app.models import ActiviteCode, KBArticle, KBArticleTable  # noqa: F401 (ActiviteCode unused, kept for symmetry)

CHUNKS_PATH = "data/processed/chunks.json"
ARTICLES_PATH = "data/processed/articles.json"

# Articles with no decision table behind them at all (confirmed during the
# 2026-10-15 proofreading pass) -- these get the FULL narrative_content.
# Everything else gets just a short intro, since its real facts live in
# decision_tables (joined via kb_article_tables).
FULL_NARRATIVE_CODES = {
    "FDE-ACT-002",
    "FDE-ALEA-RF-030",
    "FDE-TEST-JOKER-020",
    "GESICA-CLOT-024",
    "IGB-TRT-004",
    "KB-INFO-001",
    "RPR-TRAIT-026",
}

# One confirmed transcription error, fixed here rather than in the old
# chunks.json/RAG pipeline (which this script reads from but does not write
# back to). Confirmed against the real screenshot (IGB sheet, image 0 of 2):
# the technician role is "Technicien D3", not "technicien DI".
TEXT_CORRECTIONS = {
    "IGB-TRT-004": [
        ("technicien DI détecte", "technicien D3 détecte"),
        ("Le technicien DI", "Le technicien D3"),
    ],
}

NARRATIVE_CHUNK_TYPES = ("generic", "key_points", "business_case", "rule")


def apply_corrections(kb_code: str, text: str) -> str:
    for old, new in TEXT_CORRECTIONS.get(kb_code, []):
        text = text.replace(old, new)
    return text


def build_full_narrative(kb_code: str, chunks: list[dict]) -> str:
    article_chunks = [
        c for c in chunks
        if c.get("kb_code") == kb_code and c.get("chunk_type") in NARRATIVE_CHUNK_TYPES
    ]
    # Skip the bare title-only first chunk and any "transformation notes" /
    # "limites" meta-commentary chunks -- those describe the conversion
    # process, not the business content.
    skip_markers = (
        "Notes de transformation", "Notes de migration", "feuille Excel",
        "n'a pas été laissée", "doit être validé", "La feuille source",
    )
    parts = []
    for c in article_chunks:
        text = (c.get("text") or "").strip()
        if not text or text == f"{kb_code} – {c.get('article_title', '')}":
            continue
        if any(text.startswith(m) for m in skip_markers):
            continue
        parts.append(apply_corrections(kb_code, text))
    return "\n\n".join(parts)


def build_intro(kb_code: str, chunks: list[dict]) -> str:
    generic_chunks = [
        c for c in chunks
        if c.get("kb_code") == kb_code and c.get("chunk_type") == "generic"
    ]
    parts = []
    for c in generic_chunks[:2]:
        text = (c.get("text") or "").strip()
        if "–" in text and text.startswith(kb_code):
            continue  # the bare title chunk
        if text:
            parts.append(text)
        if len(parts) >= 1:
            break
    return "\n\n".join(parts)


def main() -> None:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = json.load(f)
    with open(ARTICLES_PATH, encoding="utf-8") as f:
        articles = json.load(f)

    session = SessionLocal()
    try:
        table_backed_codes = {row.kb_code for row in session.query(KBArticleTable).all()}

        for article in articles:
            kb_code = article["kb_code"]
            title = article.get("title", kb_code)

            if kb_code in FULL_NARRATIVE_CODES:
                content_scope = "full"
                narrative = build_full_narrative(kb_code, chunks)
                source_notes = (
                    "Contenu vérifié le 2026-10-15 contre les captures d'écran réelles "
                    "(voir PROGRESS.md). Aucune table de décision pour cet article -- "
                    "c'est la feuille de connaissance complète."
                )
                if kb_code in TEXT_CORRECTIONS:
                    source_notes += " Correction appliquée : technicien D3 (pas DI)."
            else:
                content_scope = "intro"
                narrative = build_intro(kb_code, chunks)
                if kb_code in table_backed_codes:
                    source_notes = (
                        "Résumé seulement -- les faits opérationnels de cet article sont "
                        "dans les decision_tables liées (voir kb_article_tables)."
                    )
                else:
                    source_notes = (
                        "Résumé seulement -- aucune decision_table liée pour le moment."
                    )

            existing = session.query(KBArticle).filter_by(kb_code=kb_code).one_or_none()
            if existing is None:
                existing = KBArticle(kb_code=kb_code)
                session.add(existing)
            existing.title = title
            existing.narrative_content = narrative
            existing.content_scope = content_scope
            existing.source_notes = source_notes

        session.commit()

        total = session.query(KBArticle).count()
        full = session.query(KBArticle).filter_by(content_scope="full").count()
        intro = session.query(KBArticle).filter_by(content_scope="intro").count()
        print(f"kb_articles populated: {total} total ({full} full, {intro} intro)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
