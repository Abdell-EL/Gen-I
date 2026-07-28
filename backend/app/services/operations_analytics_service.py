from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Chunk, RetrievalRequest, RetrievalResult, User
from app.services.admin_user_service import validate_date_range


LOW_CONFIDENCE_THRESHOLD = 0.50


def _interaction_type_expression():
    return RetrievalRequest.retriever_config_json["interaction_type"].as_string()


def _request_filters(
    *,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    user_id: int | None,
    role: str | None,
    search_type: str | None,
) -> list[Any]:
    start, end = validate_date_range(date_from, date_to)
    filters: list[Any] = []
    if start is not None:
        filters.append(RetrievalRequest.created_at >= start)
    if end is not None:
        filters.append(RetrievalRequest.created_at <= end)
    if user_id is not None:
        filters.append(RetrievalRequest.user_id == user_id)
    if role is not None:
        filters.append(func.lower(func.trim(User.role)) == role)
    if search_type is not None:
        filters.append(_interaction_type_expression() == search_type)
    return filters


def _normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def get_operations_summary(
    db: Session,
    *,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    user_id: int | None,
    role: str | None,
    search_type: str | None,
) -> dict[str, Any]:
    filters = _request_filters(
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        role=role,
        search_type=search_type,
    )
    result_stats = (
        select(
            RetrievalResult.retrieval_id.label("retrieval_id"),
            func.count(RetrievalResult.retrieval_result_id).label("results_count"),
            func.max(RetrievalResult.similarity_score).label("top_score"),
        )
        .group_by(RetrievalResult.retrieval_id)
        .subquery()
    )
    requests = db.execute(
        select(
            RetrievalRequest.retrieval_id,
            RetrievalRequest.user_id,
            RetrievalRequest.query_text,
            User.full_name,
            User.email,
            func.coalesce(result_stats.c.results_count, 0).label("results_count"),
            result_stats.c.top_score,
        )
        .join(User, User.user_id == RetrievalRequest.user_id)
        .outerjoin(result_stats, result_stats.c.retrieval_id == RetrievalRequest.retrieval_id)
        .where(*filters)
        .order_by(RetrievalRequest.retrieval_id)
    ).mappings().all()

    total_questions = len(requests)
    user_counts = Counter(row["user_id"] for row in requests)
    unique_users = len(user_counts)
    results_counts = [int(row["results_count"]) for row in requests]
    top_scores = [
        float(row["top_score"]) for row in requests if row["top_score"] is not None
    ]
    zero_result_questions = sum(count == 0 for count in results_counts)
    low_confidence_questions = sum(
        int(row["results_count"]) == 0
        or (row["top_score"] is not None and float(row["top_score"]) < LOW_CONFIDENCE_THRESHOLD)
        for row in requests
    )

    most_active_user = None
    if user_counts:
        most_active_user_id, questions_count = min(
            user_counts.items(), key=lambda item: (-item[1], item[0])
        )
        user_row = next(row for row in requests if row["user_id"] == most_active_user_id)
        most_active_user = {
            "user_id": most_active_user_id,
            "full_name": user_row["full_name"],
            "email": user_row["email"],
            "questions_count": questions_count,
        }

    normalized_counts: Counter[str] = Counter()
    normalized_examples: dict[str, str] = {}
    for row in requests:
        normalized = _normalize_question(row["query_text"])
        if not normalized:
            continue
        normalized_counts[normalized] += 1
        normalized_examples.setdefault(normalized, row["query_text"].strip())
    most_asked_question = None
    if normalized_counts:
        normalized, questions_count = min(
            normalized_counts.items(), key=lambda item: (-item[1], item[0])
        )
        most_asked_question = {
            "question": normalized_examples[normalized],
            "normalized_question": normalized,
            "questions_count": questions_count,
        }

    article_title = Chunk.metadata_json["article_title"].as_string()
    kb_code = Chunk.metadata_json["kb_code"].as_string()
    article_row = db.execute(
        select(
            article_title.label("article_title"),
            kb_code.label("kb_code"),
            func.count(RetrievalResult.retrieval_result_id).label("references_count"),
        )
        .select_from(RetrievalRequest)
        .join(User, User.user_id == RetrievalRequest.user_id)
        .join(RetrievalResult, RetrievalResult.retrieval_id == RetrievalRequest.retrieval_id)
        .join(Chunk, Chunk.chunk_id == RetrievalResult.chunk_id)
        .where(*filters, (article_title.is_not(None) | kb_code.is_not(None)))
        .group_by(article_title, kb_code)
        .order_by(
            func.count(RetrievalResult.retrieval_result_id).desc(),
            article_title.asc(),
            kb_code.asc(),
        )
        .limit(1)
    ).mappings().one_or_none()

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_questions": total_questions,
        "unique_users": unique_users,
        "active_users": unique_users,
        "average_questions_per_active_user": total_questions / unique_users if unique_users else None,
        "average_results_count": sum(results_counts) / total_questions if total_questions else None,
        "average_top_score": sum(top_scores) / len(top_scores) if top_scores else None,
        "low_confidence_questions": low_confidence_questions,
        "zero_result_questions": zero_result_questions,
        "most_active_user": most_active_user,
        "most_asked_question": most_asked_question,
        "most_consulted_article": dict(article_row) if article_row else None,
    }


def _sqlite_period_start(value: datetime, interval: str) -> datetime:
    value = value.replace(minute=0, second=0, microsecond=0)
    if interval == "hour":
        return value
    value = value.replace(hour=0)
    if interval == "day":
        return value
    if interval == "week":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def get_question_volume(
    db: Session,
    *,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    interval: str,
    user_id: int | None,
    role: str | None,
    search_type: str | None,
) -> dict[str, Any]:
    filters = _request_filters(
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        role=role,
        search_type=search_type,
    )
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        rows = db.execute(
            select(RetrievalRequest.created_at, RetrievalRequest.user_id)
            .join(User, User.user_id == RetrievalRequest.user_id)
            .where(*filters)
            .order_by(RetrievalRequest.created_at)
        ).all()
        buckets: dict[datetime, list[Any]] = {}
        for created_at, request_user_id in rows:
            period = _sqlite_period_start(created_at, interval)
            bucket = buckets.setdefault(period, [0, set()])
            bucket[0] += 1
            bucket[1].add(request_user_id)
        items = [
            {
                "period_start": period,
                "questions_count": values[0],
                "unique_users": len(values[1]),
            }
            for period, values in sorted(buckets.items())
        ]
    else:
        period_start = func.date_trunc(interval, RetrievalRequest.created_at)
        items = [
            dict(row)
            for row in db.execute(
                select(
                    period_start.label("period_start"),
                    func.count(RetrievalRequest.retrieval_id).label("questions_count"),
                    func.count(func.distinct(RetrievalRequest.user_id)).label("unique_users"),
                )
                .join(User, User.user_id == RetrievalRequest.user_id)
                .where(*filters)
                .group_by(period_start)
                .order_by(period_start)
            ).mappings()
        ]
    return {
        "interval": interval,
        "items": items,
        "date_from": date_from,
        "date_to": date_to,
    }
