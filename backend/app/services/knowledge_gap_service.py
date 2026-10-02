from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, ChatSession, KnowledgeGap, RetrievalRequest


# Phrases the assistant is instructed to use (see build_grounded_prompt in
# ollama_service.py) when the retrieved sources don't answer the question,
# plus the technical fallback messages used elsewhere in the chat pipeline.
# This is a heuristic, not a perfect classifier: it's meant to surface
# candidates for human review, not to be exhaustive on its own — that's why
# it's combined with the low-confidence signal below rather than used alone.
MISSING_INFO_PHRASES = [
    "n'est pas présente dans les sources disponibles",
    "n'est pas présent dans les sources disponibles",
    "ne sont pas disponibles",
    "je n'ai pas pu générer une réponse à partir des sources disponibles",
    "je n'ai pas trouvé de passage suffisamment pertinent",
    "n'est pas spécifié",
    "pas mentionné dans les sources",
    "n'existe pas de règle",
]

LOW_CONFIDENCE_LABELS = {"low", "unknown"}


def answer_indicates_missing_information(answer: str) -> bool:
    normalized = (answer or "").casefold()
    return any(phrase in normalized for phrase in MISSING_INFO_PHRASES)


def is_low_confidence(confidence: str | None) -> bool:
    return (confidence or "unknown") in LOW_CONFIDENCE_LABELS


def record_knowledge_gap_if_needed(
    *,
    user_id: int,
    question_text: str,
    answer_text: str,
    confidence: str | None,
    session_id: int | None = None,
    retrieval_id: int | None = None,
    assistant_message_id: int | None = None,
) -> int | None:
    text_indicates_missing = answer_indicates_missing_information(answer_text)
    low_confidence = is_low_confidence(confidence)

    if not text_indicates_missing and not low_confidence:
        return None

    db = SessionLocal()
    try:
        gap = KnowledgeGap(
            session_id=session_id,
            retrieval_id=retrieval_id,
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            question_text=question_text,
            answer_text=answer_text,
            confidence_label=confidence,
            text_indicates_missing=text_indicates_missing,
            low_confidence=low_confidence,
        )
        db.add(gap)
        db.commit()
        db.refresh(gap)
        return gap.gap_id
    finally:
        db.close()


class FeedbackMessageNotFoundError(Exception):
    pass


def flag_knowledge_gap_from_feedback(db: Session, *, message_id: int) -> int:
    """Record (or mark) a knowledge gap from a negative user feedback rating.

    A user clicking "not helpful" / "partially helpful" in the chat UI is a
    third, independent signal alongside the two automatic ones (the model's
    own wording, and retrieval confidence) — sometimes the model confidently
    answers from a fragment of the question without actually knowing the
    answer, which neither automatic signal reliably catches. If an automatic
    gap already exists for this exact message, this just marks it as also
    user-flagged rather than creating a duplicate row.
    """
    existing = (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.assistant_message_id == message_id)
        .first()
    )
    if existing is not None:
        existing.user_flagged = True
        db.commit()
        return existing.gap_id

    assistant_message = db.get(ChatMessage, message_id)
    if assistant_message is None:
        raise FeedbackMessageNotFoundError(f"Message {message_id} not found")

    session = db.get(ChatSession, assistant_message.session_id)

    question = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == assistant_message.session_id,
            ChatMessage.role == "user",
            ChatMessage.message_id < assistant_message.message_id,
        )
        .order_by(ChatMessage.message_id.desc())
        .first()
    )
    retrieval = (
        db.query(RetrievalRequest)
        .filter(RetrievalRequest.message_id == question.message_id)
        .first()
        if question is not None
        else None
    )

    gap = KnowledgeGap(
        session_id=assistant_message.session_id,
        retrieval_id=retrieval.retrieval_id if retrieval else None,
        assistant_message_id=message_id,
        user_id=session.user_id if session else None,
        question_text=question.content if question else "(question introuvable)",
        answer_text=assistant_message.content,
        confidence_label=None,
        text_indicates_missing=False,
        low_confidence=False,
        user_flagged=True,
    )
    db.add(gap)
    db.commit()
    db.refresh(gap)
    return gap.gap_id


def _serialize(gap: KnowledgeGap) -> dict[str, Any]:
    return {
        "gap_id": gap.gap_id,
        "session_id": gap.session_id,
        "retrieval_id": gap.retrieval_id,
        "assistant_message_id": gap.assistant_message_id,
        "user_id": gap.user_id,
        "question_text": gap.question_text,
        "answer_text": gap.answer_text,
        "confidence_label": gap.confidence_label,
        "text_indicates_missing": gap.text_indicates_missing,
        "low_confidence": gap.low_confidence,
        "user_flagged": gap.user_flagged,
        "status": gap.status,
        "created_at": gap.created_at,
        "resolved_at": gap.resolved_at,
        "resolved_by": gap.resolved_by,
        "resolution_notes": gap.resolution_notes,
    }


def list_knowledge_gaps(
    db: Session,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    query = db.query(KnowledgeGap)
    if status:
        query = query.filter(KnowledgeGap.status == status)
    total = query.count()
    rows = (
        query.order_by(KnowledgeGap.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": [_serialize(row) for row in rows],
    }


class KnowledgeGapNotFoundError(Exception):
    pass


def resolve_knowledge_gap(
    db: Session,
    *,
    gap_id: int,
    resolved_by: int,
    resolution_notes: str | None,
    status: str = "resolved",
) -> dict[str, Any]:
    gap = db.get(KnowledgeGap, gap_id)
    if gap is None:
        raise KnowledgeGapNotFoundError(f"Knowledge gap {gap_id} not found")
    gap.status = status
    gap.resolved_by = resolved_by
    gap.resolution_notes = resolution_notes
    gap.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(gap)
    return _serialize(gap)
