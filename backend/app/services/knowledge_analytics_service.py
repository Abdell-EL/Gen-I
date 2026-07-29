from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from math import ceil, floor

from sqlalchemy import func, select

from app.models import (ChatMessage, ChatSession, Chunk, DocumentVersion,
                        RetrievalRequest, RetrievalResult, SourceDocument, User)
from app.services.admin_user_service import validate_date_range
from app.services.analytics_hygiene import canonicalize_question, is_benchmark_question


def _search_type(config):
    return config.get("interaction_type") if isinstance(config, dict) else None


def _request_rows(db, *, date_from=None, date_to=None, user_id=None, role=None,
                  search_type=None, include_benchmarks=True):
    start, end = validate_date_range(date_from, date_to)
    filters = []
    if start is not None:
        filters.append(RetrievalRequest.created_at >= start)
    if end is not None:
        filters.append(RetrievalRequest.created_at <= end)
    if user_id is not None:
        filters.append(RetrievalRequest.user_id == user_id)
    if role is not None:
        filters.append(func.lower(func.trim(User.role)) == role)
    rows = db.execute(select(
        RetrievalRequest.retrieval_id, RetrievalRequest.message_id,
        RetrievalRequest.user_id, RetrievalRequest.query_text,
        RetrievalRequest.top_k, RetrievalRequest.created_at,
        RetrievalRequest.retriever_config_json, User.full_name, User.email, User.role,
    ).join(User, User.user_id == RetrievalRequest.user_id).where(*filters).order_by(
        RetrievalRequest.created_at, RetrievalRequest.retrieval_id
    )).mappings()
    items = [dict(row) for row in rows]
    if search_type is not None:
        items = [row for row in items
                 if _search_type(row["retriever_config_json"]) == search_type]
    if not include_benchmarks:
        items = [row for row in items if not is_benchmark_question(row["query_text"])]
    return items


def _result_rows(db, retrieval_ids):
    if not retrieval_ids:
        return []
    rows = db.execute(select(
        RetrievalResult.retrieval_result_id, RetrievalResult.retrieval_id,
        RetrievalResult.similarity_score, RetrievalResult.rank,
        RetrievalResult.chunk_id, Chunk.chunk_type, Chunk.metadata_json,
    ).join(Chunk, Chunk.chunk_id == RetrievalResult.chunk_id).where(
        RetrievalResult.retrieval_id.in_(retrieval_ids)
    ).order_by(RetrievalResult.retrieval_id, RetrievalResult.rank,
               RetrievalResult.retrieval_result_id)).mappings()
    return [dict(row) for row in rows]


def _requests_with_results(db, **filters):
    requests = _request_rows(db, **filters)
    grouped = defaultdict(list)
    for row in _result_rows(db, [item["retrieval_id"] for item in requests]):
        grouped[row["retrieval_id"]].append(row)
    return requests, grouped


def get_trending_questions(db, *, date_from, date_to, user_id, role, search_type,
                           previous_period, limit, include_benchmarks):
    current = _request_rows(db, date_from=date_from, date_to=date_to, user_id=user_id,
                            role=role, search_type=search_type,
                            include_benchmarks=include_benchmarks)
    previous = []
    start, end = validate_date_range(date_from, date_to)
    if previous_period and start is not None and end is not None:
        duration = end - start
        previous_end = start - timedelta(microseconds=1)
        previous = _request_rows(
            db, date_from=previous_end - duration, date_to=previous_end,
            user_id=user_id, role=role, search_type=search_type,
            include_benchmarks=include_benchmarks,
        )
    groups, old_counts = defaultdict(list), defaultdict(int)
    for row in current:
        normalized = canonicalize_question(row["query_text"])
        if normalized:
            groups[normalized].append(row)
    for row in previous:
        normalized = canonicalize_question(row["query_text"])
        if normalized:
            old_counts[normalized] += 1
    items = []
    for normalized, rows in groups.items():
        latest = max(rows, key=lambda row: (row["created_at"], row["retrieval_id"]))
        current_count, previous_count = len(rows), old_counts[normalized]
        items.append({
            "question": latest["query_text"].strip(),
            "normalized_question": normalized,
            "current_count": current_count, "previous_count": previous_count,
            "absolute_change": current_count - previous_count,
            "percentage_change": ((current_count - previous_count) / previous_count * 100
                                  if previous_count else None),
            "unique_users": len({row["user_id"] for row in rows}),
            "last_asked_at": latest["created_at"],
        })
    items.sort(key=lambda item: (-item["current_count"], -item["absolute_change"],
                                 item["normalized_question"]))
    return {"items": items[:limit], "date_from": date_from, "date_to": date_to,
            "previous_period": previous_period,
            "include_benchmarks": include_benchmarks}


def get_low_confidence(db, *, threshold, include_zero_results, page, page_size,
                       **filters):
    requests, results = _requests_with_results(db, **filters)
    items = []
    for request in requests:
        rows = results[request["retrieval_id"]]
        if not rows:
            if not include_zero_results:
                continue
            reason, top = "zero_results", None
        else:
            top = max(rows, key=lambda row: (row["similarity_score"], -row["rank"],
                                             -row["retrieval_result_id"]))
            if float(top["similarity_score"]) >= threshold:
                continue
            reason = "top_score_below_threshold"
        metadata = top["metadata_json"] if top and isinstance(top["metadata_json"], dict) else {}
        items.append({
            "retrieval_id": request["retrieval_id"], "query_text": request["query_text"],
            "created_at": request["created_at"],
            "user": {"id": request["user_id"], "name": request["full_name"],
                     "email": request["email"], "role": request["role"]},
            "search_type": _search_type(request["retriever_config_json"]),
            "results_count": len(rows),
            "top_score": float(top["similarity_score"]) if top else None,
            "average_score": (sum(float(row["similarity_score"]) for row in rows) / len(rows)
                              if rows else None),
            "low_confidence_reason": reason,
            "top_article_title": metadata.get("article_title"),
            "top_kb_code": metadata.get("kb_code"),
        })
    items.sort(key=lambda item: (item["created_at"], item["retrieval_id"]), reverse=True)
    total, offset = len(items), (page - 1) * page_size
    return {"items": items[offset:offset + page_size], "page": page,
            "page_size": page_size, "total": total,
            "pages": ceil(total / page_size) if total else 0,
            "threshold": threshold, "include_zero_results": include_zero_results,
            "include_benchmarks": filters.get("include_benchmarks", True)}


def get_score_distribution(db, *, bucket_size, score_basis, **filters):
    requests, grouped = _requests_with_results(db, **filters)
    scores = []
    for request in requests:
        rows = grouped[request["retrieval_id"]]
        if score_basis == "top_score" and rows:
            scores.append(max(float(row["similarity_score"]) for row in rows))
        elif score_basis == "all_results":
            scores.extend(float(row["similarity_score"]) for row in rows)
    bucket_count, counts = round(1 / bucket_size), [0] * round(1 / bucket_size)
    for score in scores:
        clamped = min(1.0, max(0.0, score))
        counts[min(bucket_count - 1, floor(clamped / bucket_size))] += 1
    total = len(scores)
    buckets = [{"lower_bound": round(index * bucket_size, 10),
                "upper_bound": round(min(1.0, (index + 1) * bucket_size), 10),
                "count": count, "percentage": count * 100 / total if total else 0.0}
               for index, count in enumerate(counts)]
    return {"bucket_size": bucket_size, "score_basis": score_basis,
            "total": total, "buckets": buckets,
            "include_benchmarks": filters.get("include_benchmarks", True)}


def get_article_analytics(db, *, search, page, page_size, sort_by, sort_order,
                          **filters):
    requests, grouped = _requests_with_results(db, **filters)
    request_map = {row["retrieval_id"]: row for row in requests}
    groups = defaultdict(list)
    for retrieval_id, rows in grouped.items():
        for result in rows:
            metadata = result["metadata_json"] if isinstance(result["metadata_json"], dict) else {}
            title, code = metadata.get("article_title"), metadata.get("kb_code")
            if title is not None or code is not None:
                groups[(title, code)].append((result, request_map[retrieval_id]))
    needle, items = search.strip().lower() if search else "", []
    for (title, code), rows in groups.items():
        if needle and needle not in (title or "").lower() and needle not in (code or "").lower():
            continue
        scores = [float(result["similarity_score"]) for result, _ in rows]
        items.append({
            "article_title": title, "kb_code": code, "consultation_count": len(rows),
            "unique_requests": len({request["retrieval_id"] for _, request in rows}),
            "unique_users": len({request["user_id"] for _, request in rows}),
            "average_score": sum(scores) / len(scores), "top_score": max(scores),
            "last_consulted_at": max(request["created_at"] for _, request in rows),
        })
    items.sort(key=lambda item: ((item["article_title"] or "").lower(), item["kb_code"] or ""))
    items.sort(key=lambda item: ((item[sort_by] or "").lower()
                                 if sort_by == "article_title" else item[sort_by]),
               reverse=sort_order == "desc")
    total, offset = len(items), (page - 1) * page_size
    return {"items": items[offset:offset + page_size], "page": page,
            "page_size": page_size, "total": total,
            "pages": ceil(total / page_size) if total else 0}


def get_unreferenced_content(db, *, date_from, date_to, search, page, page_size):
    start, end = validate_date_range(date_from, date_to)
    documents = db.execute(select(SourceDocument).order_by(SourceDocument.document_id)).scalars().all()
    versions_by_doc = defaultdict(list)
    for row in db.execute(select(DocumentVersion.version_id, DocumentVersion.document_id,
                                 DocumentVersion.is_current)).mappings():
        versions_by_doc[row["document_id"]].append(dict(row))
    chunks_by_version, chunk_to_version = defaultdict(list), {}
    for row in db.execute(select(Chunk.chunk_id, Chunk.version_id, Chunk.metadata_json)).mappings():
        chunks_by_version[row["version_id"]].append(dict(row))
        chunk_to_version[row["chunk_id"]] = row["version_id"]
    reference_filters = []
    if start is not None:
        reference_filters.append(RetrievalRequest.created_at >= start)
    if end is not None:
        reference_filters.append(RetrievalRequest.created_at <= end)
    referenced_versions = set()
    for chunk_id, _created_at in db.execute(select(
        RetrievalResult.chunk_id, RetrievalRequest.created_at
    ).join(RetrievalRequest, RetrievalRequest.retrieval_id == RetrievalResult.retrieval_id)
      .where(*reference_filters)):
        if chunk_id in chunk_to_version:
            referenced_versions.add(chunk_to_version[chunk_id])
    needle, items = search.strip().lower() if search else "", []
    for document in documents:
        doc_versions = versions_by_doc[document.document_id]
        if any(row["version_id"] in referenced_versions for row in doc_versions):
            continue
        current_ids = {row["version_id"] for row in doc_versions
                       if document.current_version_id == row["version_id"] or
                       (document.current_version_id is None and row["is_current"])}
        current_chunks = [chunk for version_id in current_ids
                          for chunk in chunks_by_version[version_id]]
        metadata = next((chunk["metadata_json"] for chunk in current_chunks
                         if isinstance(chunk["metadata_json"], dict)), {})
        title, code = metadata.get("article_title"), metadata.get("kb_code")
        if needle and needle not in " ".join((document.file_name, title or "", code or "")).lower():
            continue
        items.append({"source_document_id": document.document_id,
                      "filename": document.file_name, "title": title, "kb_code": code,
                      "current_version_chunk_count": len(current_chunks),
                      "created_at": document.created_at, "last_referenced_at": None,
                      "reference_count": 0})
    items.sort(key=lambda item: ((item["title"] or item["filename"]).lower(),
                                 item["source_document_id"]))
    total, offset = len(items), (page - 1) * page_size
    return {"items": items[offset:offset + page_size], "page": page,
            "page_size": page_size, "total": total,
            "pages": ceil(total / page_size) if total else 0,
            "date_from": date_from, "date_to": date_to}


def get_retrieval_drill_down(db, retrieval_id):
    request = db.execute(select(
        RetrievalRequest.retrieval_id, RetrievalRequest.query_text,
        RetrievalRequest.created_at, RetrievalRequest.top_k,
        RetrievalRequest.message_id, RetrievalRequest.retriever_config_json,
        User.user_id, User.full_name, User.email, User.role, ChatSession.session_id,
    ).join(User, User.user_id == RetrievalRequest.user_id)
      .outerjoin(ChatMessage, ChatMessage.message_id == RetrievalRequest.message_id)
      .outerjoin(ChatSession, ChatSession.session_id == ChatMessage.session_id)
      .where(RetrievalRequest.retrieval_id == retrieval_id)).mappings().one_or_none()
    if request is None:
        return None
    results = []
    for row in _result_rows(db, [retrieval_id]):
        metadata = row["metadata_json"] if isinstance(row["metadata_json"], dict) else {}
        results.append({"rank": row["rank"], "score": row["similarity_score"],
                        "chunk_external_id": metadata.get("external_chunk_id"),
                        "article_title": metadata.get("article_title"),
                        "kb_code": metadata.get("kb_code"),
                        "section_title": metadata.get("section_title"),
                        "chunk_type": row["chunk_type"] or metadata.get("chunk_type"),
                        "priority": metadata.get("priority")})
    return {"retrieval_id": request["retrieval_id"], "query_text": request["query_text"],
            "created_at": request["created_at"], "top_k": request["top_k"],
            "user": {"id": request["user_id"], "name": request["full_name"],
                     "email": request["email"], "role": request["role"]},
            "search_type": _search_type(request["retriever_config_json"]),
            "result_count": len(results), "session_id": request["session_id"],
            "message_id": request["message_id"], "results": results}
