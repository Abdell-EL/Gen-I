from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth_dependencies import require_any_role, require_role
from app.database import get_db
from app.models import (ChatMessage, ChatSession, Chunk, MessageFeedback,
                        RetrievalRequest, RetrievalResult, User)
from app.services.admin_user_service import validate_date_range

Rating = Literal["helpful", "partially_helpful", "not_helpful"]
Reason = Literal["incorrect_answer", "incomplete_answer", "irrelevant_sources",
                 "missing_information", "unclear_answer", "outdated_information", "other"]
RATING_TO_INT = {"not_helpful": 1, "partially_helpful": 2, "helpful": 3}
INT_TO_RATING = {value: key for key, value in RATING_TO_INT.items()}

router = APIRouter()
member = require_any_role("admin", "agent")
admin = require_role("admin")


class FeedbackRequest(BaseModel):
    rating: Rating
    reason: Reason | None = None
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 1000:
            raise ValueError("Comment must not exceed 1000 characters.")
        return value or None

    @model_validator(mode="after")
    def validate_negative(self):
        if self.rating != "helpful" and self.reason is None:
            raise ValueError("A reason is required for partial or negative feedback.")
        if self.reason == "other" and not self.comment:
            raise ValueError("A comment is required when reason is other.")
        return self


class FeedbackResponse(BaseModel):
    feedback_id: int
    message_id: int
    user_id: int
    rating: Rating
    reason: Reason | None
    comment: str | None
    created_at: datetime
    updated_at: datetime
    was_updated: bool


def _envelope(row: MessageFeedback):
    try:
        value = json.loads(row.feedback_text or "{}")
        if isinstance(value, dict) and value.get("version") == 1:
            return value
    except (TypeError, json.JSONDecodeError):
        pass
    return {"version": 1, "reason": None, "comment": row.feedback_text,
            "updated_at": row.created_at.isoformat() if row.created_at else None}


def _serialize(row, *, was_updated=False):
    payload = _envelope(row)
    updated = payload.get("updated_at")
    return {"feedback_id": row.feedback_id, "message_id": row.message_id,
            "user_id": row.user_id, "rating": INT_TO_RATING.get(row.rating, "not_helpful"),
            "reason": payload.get("reason"), "comment": payload.get("comment"),
            "created_at": row.created_at,
            "updated_at": datetime.fromisoformat(updated) if updated else row.created_at,
            "was_updated": was_updated}


def _message(db, message_id, user, *, hide=False):
    row = db.execute(select(ChatMessage, ChatSession).join(
        ChatSession, ChatSession.session_id == ChatMessage.session_id
    ).where(ChatMessage.message_id == message_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "Message not found.")
    message, session = row
    if message.role != "assistant":
        raise HTTPException(422, "Feedback may only target an assistant message.")
    if user.role != "admin" and session.user_id != user.user_id:
        raise HTTPException(404 if hide else 403, "Message is not accessible.")
    return message, session


@router.post("/chat/messages/{message_id}/feedback", response_model=FeedbackResponse)
def submit_feedback(request: FeedbackRequest, message_id: int = Path(ge=1),
                    current_user: User = Depends(member), db: Session = Depends(get_db)):
    _message(db, message_id, current_user)
    row = db.execute(select(MessageFeedback).where(
        MessageFeedback.message_id == message_id,
        MessageFeedback.user_id == current_user.user_id,
    ).order_by(MessageFeedback.feedback_id)).scalars().first()
    was_updated = row is not None
    now = datetime.now(timezone.utc)
    if row is None:
        row = MessageFeedback(message_id=message_id, user_id=current_user.user_id,
                              created_at=now)
        db.add(row)
    row.rating = RATING_TO_INT[request.rating]
    row.is_incorrect = request.reason == "incorrect_answer"
    row.feedback_text = json.dumps({"version": 1, "reason": request.reason,
                                    "comment": request.comment, "updated_at": now.isoformat()})
    db.commit(); db.refresh(row)
    return _serialize(row, was_updated=was_updated)


@router.get("/chat/messages/{message_id}/feedback", response_model=FeedbackResponse)
def read_feedback(message_id: int = Path(ge=1), current_user: User = Depends(member),
                  db: Session = Depends(get_db)):
    _message(db, message_id, current_user, hide=True)
    query = select(MessageFeedback).where(MessageFeedback.message_id == message_id)
    if current_user.role != "admin":
        query = query.where(MessageFeedback.user_id == current_user.user_id)
    else:
        query = query.order_by((MessageFeedback.user_id == current_user.user_id).desc(),
                               MessageFeedback.feedback_id)
    row = db.execute(query).scalars().first()
    if row is None:
        raise HTTPException(404, "Feedback not found.")
    return _serialize(row)


@router.delete("/chat/messages/{message_id}/feedback", status_code=204)
def delete_feedback(message_id: int = Path(ge=1), current_user: User = Depends(member),
                    db: Session = Depends(get_db)):
    _message(db, message_id, current_user, hide=True)
    row = db.execute(select(MessageFeedback).where(
        MessageFeedback.message_id == message_id,
        MessageFeedback.user_id == current_user.user_id,
    )).scalars().first()
    if row is None:
        raise HTTPException(404, "Feedback not found.")
    db.delete(row); db.commit()
    return Response(status_code=204)


def _analytics_rows(db, *, date_from=None, date_to=None, rating=None, reason=None,
                    user_id=None, search_type=None, article=None, search=None):
    start, end = validate_date_range(date_from, date_to)
    conditions = []
    if start: conditions.append(MessageFeedback.created_at >= start)
    if end: conditions.append(MessageFeedback.created_at <= end)
    if user_id: conditions.append(MessageFeedback.user_id == user_id)
    base = [dict(row) for row in db.execute(select(
        MessageFeedback.feedback_id, MessageFeedback.message_id, MessageFeedback.user_id,
        MessageFeedback.rating, MessageFeedback.feedback_text, MessageFeedback.created_at,
        ChatMessage.content.label("answer"), ChatMessage.session_id,
        User.full_name, User.email, User.role,
    ).join(ChatMessage, ChatMessage.message_id == MessageFeedback.message_id)
      .join(User, User.user_id == MessageFeedback.user_id).where(*conditions)
      .order_by(MessageFeedback.feedback_id)).mappings()]
    session_ids = list({row["session_id"] for row in base})
    questions = {}
    retrievals = {}
    if session_ids:
        for row in db.execute(select(ChatMessage.message_id, ChatMessage.session_id,
                                     ChatMessage.content, ChatMessage.created_at)
                              .where(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "user")
                              .order_by(ChatMessage.session_id, ChatMessage.created_at,
                                        ChatMessage.message_id)).mappings():
            questions[row["session_id"]] = dict(row)
        question_ids = [row["message_id"] for row in questions.values()]
        if question_ids:
            for row in db.execute(select(RetrievalRequest).where(
                RetrievalRequest.message_id.in_(question_ids))).scalars():
                retrievals[row.message_id] = row
    result_map = {}
    retrieval_ids = [row.retrieval_id for row in retrievals.values()]
    if retrieval_ids:
        for row in db.execute(select(RetrievalResult, Chunk).join(
            Chunk, Chunk.chunk_id == RetrievalResult.chunk_id
        ).where(RetrievalResult.retrieval_id.in_(retrieval_ids)).order_by(
            RetrievalResult.retrieval_id, RetrievalResult.rank,
            RetrievalResult.retrieval_result_id)).all():
            result_map.setdefault(row[0].retrieval_id, []).append(row)
    items = []
    for row in base:
        try:
            payload = json.loads(row["feedback_text"] or "{}") if row["feedback_text"] else {}
            if not isinstance(payload, dict):
                payload = {"comment": row["feedback_text"]}
        except (TypeError, json.JSONDecodeError):
            payload = {"comment": row["feedback_text"]}
        value_rating = INT_TO_RATING.get(row["rating"], "not_helpful")
        value_reason = payload.get("reason")
        question = questions.get(row["session_id"])
        retrieval = retrievals.get(question["message_id"]) if question else None
        results = result_map.get(retrieval.retrieval_id, []) if retrieval else []
        articles = []
        groups = {}
        for result, chunk in results:
            meta = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            key = (meta.get("article_title"), meta.get("kb_code"))
            groups[key] = max(groups.get(key, float("-inf")), result.similarity_score)
        for (title, code), top in groups.items():
            articles.append({"article_title": title, "kb_code": code, "top_score": top})
        interaction = (retrieval.retriever_config_json or {}).get("interaction_type") if retrieval else None
        item = {**row, "rating_name": value_rating, "reason": value_reason,
                "comment": payload.get("comment"), "updated_at": payload.get("updated_at"),
                "question": question["content"] if question else None,
                "retrieval_id": retrieval.retrieval_id if retrieval else None,
                "search_type": interaction, "articles": articles, "results": results}
        haystack = " ".join(str(value or "") for value in (
            item["question"], item["comment"], item["full_name"], item["email"],
            *[x for article_item in articles for x in (article_item["article_title"], article_item["kb_code"])])).lower()
        article_haystack = " ".join(str(x or "") for a in articles for x in (a["article_title"], a["kb_code"])).lower()
        if rating and value_rating != rating: continue
        if reason and value_reason != reason: continue
        if search_type and interaction != search_type: continue
        if article and article.lower() not in article_haystack: continue
        if search and search.lower().strip() not in haystack: continue
        items.append(item)
    return items


def _list_item(row, include_results=False):
    value = {"feedback_id": row["feedback_id"], "created_at": row["created_at"],
             "updated_at": row["updated_at"] or row["created_at"], "rating": row["rating_name"],
             "reason": row["reason"], "comment": row["comment"],
             "user": {"id": row["user_id"], "full_name": row["full_name"],
                      "email": row["email"], "role": row["role"]},
             "message_id": row["message_id"], "session_id": row["session_id"],
             "retrieval_id": row["retrieval_id"], "question": row["question"],
             "answer": row["answer"] if include_results else row["answer"][:4000],
             "search_type": row["search_type"], "confidence": None,
             "referenced_articles": row["articles"], "result_count": len(row["results"])}
    if include_results:
        value["results"] = [{"rank": result.rank, "score": result.similarity_score,
                             "chunk_external_id": (chunk.metadata_json or {}).get("external_chunk_id"),
                             "article_title": (chunk.metadata_json or {}).get("article_title"),
                             "kb_code": (chunk.metadata_json or {}).get("kb_code"),
                             "section_title": (chunk.metadata_json or {}).get("section_title"),
                             "chunk_type": chunk.chunk_type,
                             "priority": (chunk.metadata_json or {}).get("priority")}
                            for result, chunk in row["results"]]
    return value


def _filter_params(date_from, date_to, rating, reason, user_id, search_type, article):
    return dict(date_from=date_from, date_to=date_to, rating=rating, reason=reason,
                user_id=user_id, search_type=search_type, article=article)


@router.get("/admin/analytics/feedback/summary")
def feedback_summary(date_from: date | datetime | None = None, date_to: date | datetime | None = None,
                     rating: Rating | None = None, reason: Reason | None = None,
                     user_id: int | None = Query(None, ge=1),
                     search_type: Literal["search", "keyword_search", "chat"] | None = None,
                     article: str | None = None, _user: User = Depends(admin), db: Session = Depends(get_db)):
    try: validate_date_range(date_from, date_to)
    except ValueError as error: raise HTTPException(422, str(error)) from None
    params = _filter_params(date_from, date_to, rating, reason, user_id, search_type, article)
    rows = _analytics_rows(db, **params)
    counts = {name: sum(row["rating_name"] == name for row in rows) for name in RATING_TO_INT}
    negative = [row for row in rows if row["rating_name"] != "helpful"]
    reasons = {}
    affected = {}
    for row in negative:
        if row["reason"]: reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        for item in row["articles"]:
            key = (item["article_title"], item["kb_code"])
            affected[key] = affected.get(key, 0) + 1
    common = min(reasons, key=lambda key: (-reasons[key], key)) if reasons else None
    top = min(affected, key=lambda key: (-affected[key], str(key))) if affected else None
    total = len(rows)
    trend = None
    start, end = validate_date_range(date_from, date_to)
    if start and end:
        previous_end = start - timedelta(microseconds=1)
        previous = _analytics_rows(db, **{**params, "date_from": previous_end - (end-start), "date_to": previous_end})
        trend = {"current_total": total, "previous_total": len(previous),
                 "absolute_change": total-len(previous),
                 "percentage_change": ((total-len(previous))/len(previous)*100 if previous else None)}
    return {"total_feedback": total, "helpful_count": counts["helpful"],
            "partially_helpful_count": counts["partially_helpful"],
            "not_helpful_count": counts["not_helpful"],
            "helpful_percentage": counts["helpful"]*100/total if total else 0,
            "negative_percentage": len(negative)*100/total if total else 0,
            "feedback_unique_users": len({row["user_id"] for row in rows}),
            "feedback_unique_messages": len({row["message_id"] for row in rows}),
            "most_common_negative_reason": common,
            "most_affected_article": ({"article_title": top[0], "kb_code": top[1],
                                       "negative_feedback_count": affected[top]} if top else None),
            "trend": trend}


@router.get("/admin/analytics/feedback")
def feedback_list(date_from: date | datetime | None = None, date_to: date | datetime | None = None,
                  rating: Rating | None = None, reason: Reason | None = None,
                  user_id: int | None = Query(None, ge=1),
                  search_type: Literal["search", "keyword_search", "chat"] | None = None,
                  article: str | None = None, search: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  sort_by: Literal["created_at", "rating", "user", "question"] = "created_at",
                  sort_order: Literal["asc", "desc"] = "desc",
                  _user: User = Depends(admin), db: Session = Depends(get_db)):
    try: validate_date_range(date_from, date_to)
    except ValueError as error: raise HTTPException(422, str(error)) from None
    rows = _analytics_rows(db, **_filter_params(date_from, date_to, rating, reason, user_id,
                                                search_type, article), search=search)
    key = {"created_at": lambda x: x["created_at"], "rating": lambda x: x["rating"],
           "user": lambda x: x["full_name"].lower(),
           "question": lambda x: (x["question"] or "").lower()}[sort_by]
    rows.sort(key=lambda x: x["feedback_id"])
    rows.sort(key=key, reverse=sort_order == "desc")
    total = len(rows); offset = (page-1)*page_size
    return {"items": [_list_item(row) for row in rows[offset:offset+page_size]],
            "page": page, "page_size": page_size, "total": total,
            "pages": ceil(total/page_size) if total else 0}


@router.get("/admin/analytics/feedback/{feedback_id}")
def feedback_detail(feedback_id: int = Path(ge=1), _user: User = Depends(admin),
                    db: Session = Depends(get_db)):
    rows = _analytics_rows(db)
    row = next((row for row in rows if row["feedback_id"] == feedback_id), None)
    if row is None: raise HTTPException(404, "Feedback not found.")
    return _list_item(row, include_results=True)
