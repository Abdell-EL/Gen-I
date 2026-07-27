import re
from typing import Any


CODE_PATTERNS = [
    r"code situation\s*:?\s*([A-Z0-9]{1,10})",
    r"associer le code situation\s+([A-Z0-9]{1,10})",
]


def extract_code_situation(text: str) -> str | None:
    if not text:
        return None

    for pattern in CODE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()

    return None


def confidence_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.70:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def compose_answer(question: str, retrieved_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not retrieved_chunks:
        return {
            "answer": (
                "Je n’ai pas trouvé de passage suffisamment pertinent dans la base de connaissances "
                "pour répondre à cette question."
            ),
            "confidence": "low",
            "sources": [],
        }

    best_chunk = retrieved_chunks[0]
    best_text = best_chunk.get("text", "")
    best_score = best_chunk.get("score")

    code = extract_code_situation(best_text)

    if code is None:
        for chunk in retrieved_chunks:
            code = extract_code_situation(chunk.get("text", ""))
            if code:
                best_chunk = chunk
                best_text = chunk.get("text", "")
                best_score = chunk.get("score")
                break

    if code:
        answer = (
            f"Le code situation à utiliser est **{code}**.\n\n"
            f"Justification : {best_text}"
        )
    else:
        answer = (
            "Voici le passage le plus pertinent retrouvé dans la base de connaissances :\n\n"
            f"{best_text}"
        )

    sources = [
        {
            "rank": chunk.get("rank"),
            "score": chunk.get("score"),
            "id": chunk.get("id"),
            "kb_code": chunk.get("kb_code"),
            "article_title": chunk.get("article_title"),
            "section_title": chunk.get("section_title"),
            "chunk_type": chunk.get("chunk_type"),
            "priority": chunk.get("priority"),
            "text": chunk.get("text"),
        }
        for chunk in retrieved_chunks
    ]

    return {
        "answer": answer,
        "confidence": confidence_label(best_score),
        "sources": sources,
    }