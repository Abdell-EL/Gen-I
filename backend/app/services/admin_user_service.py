from __future__ import annotations

from datetime import date, datetime, time, timezone
from math import ceil
from typing import Any

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.admin_schemas import CreateUserRequest, UpdateUserRequest
from app.models import AuditLog, RetrievalRequest, User
from app.security import hash_password
from app.services.auth_service import normalize_email


EMAIL_CONFLICT = "A user with this email already exists."
USER_NOT_FOUND = "User not found."
SELF_DEACTIVATION_CONFLICT = "Administrators cannot deactivate their own account."
SELF_DEMOTION_CONFLICT = "Administrators cannot remove their own admin role."
FINAL_ADMIN_CONFLICT = "The final active administrator cannot be deactivated or demoted."
PERSISTENCE_CONFLICT = "The user change conflicts with existing data."


class AdminUserNotFoundError(Exception):
    pass


class AdminUserConflictError(Exception):
    pass


def _role_expression():
    return func.lower(func.trim(User.role))


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise AdminUserNotFoundError(USER_NOT_FOUND)
    return user


def _email_exists(db: Session, email: str, *, exclude_user_id: int | None = None) -> bool:
    statement = select(User.user_id).where(func.lower(User.email) == email)
    if exclude_user_id is not None:
        statement = statement.where(User.user_id != exclude_user_id)
    return db.execute(statement.limit(1)).scalar_one_or_none() is not None


def _add_audit(
    db: Session,
    *,
    actor_user_id: int,
    action: str,
    target_user_id: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=actor_user_id,
            action=action,
            entity_type="user",
            entity_id=target_user_id,
            method_json=metadata or {},
        )
    )


def list_users(
    db: Session,
    *,
    page: int,
    page_size: int,
    search: str | None,
    role: str | None,
    is_active: bool | None,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    filters = []
    normalized_search = search.strip() if search else ""
    if normalized_search:
        pattern = f"%{normalized_search.lower()}%"
        filters.append(
            or_(
                func.lower(User.full_name).like(pattern),
                func.lower(User.email).like(pattern),
            )
        )
    if role is not None:
        filters.append(_role_expression() == role)
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))

    total = db.execute(select(func.count(User.user_id)).where(*filters)).scalar_one()
    columns = {
        "created_at": User.created_at,
        "full_name": User.full_name,
        "email": User.email,
        "role": User.role,
    }
    order = asc if sort_order == "asc" else desc
    statement = (
        select(User)
        .where(*filters)
        .order_by(order(columns[sort_by]), asc(User.user_id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(db.execute(statement).scalars().all())
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": ceil(total / page_size) if total else 0,
    }


def get_user(db: Session, user_id: int) -> User:
    return _get_user(db, user_id)


def create_user(
    db: Session,
    *,
    actor_user_id: int,
    request: CreateUserRequest,
) -> User:
    email = normalize_email(str(request.email))
    if _email_exists(db, email):
        raise AdminUserConflictError(EMAIL_CONFLICT)

    user = User(
        full_name=request.full_name,
        email=email,
        password_hash=hash_password(request.password),
        role=request.role,
        department_id=request.department_id,
        is_active=request.is_active,
    )
    try:
        db.add(user)
        db.flush()
        _add_audit(
            db,
            actor_user_id=actor_user_id,
            action="user.created",
            target_user_id=user.user_id,
            metadata={"role": user.role, "is_active": user.is_active},
        )
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise AdminUserConflictError(EMAIL_CONFLICT) from None
    except Exception:
        db.rollback()
        raise


def _lock_active_admin_ids(db: Session) -> list[int]:
    statement = (
        select(User.user_id)
        .where(User.is_active.is_(True), _role_expression() == "admin")
        .with_for_update()
    )
    return list(db.execute(statement).scalars().all())


def update_user(
    db: Session,
    *,
    actor_user_id: int,
    target_user_id: int,
    request: UpdateUserRequest,
) -> User:
    user = _get_user(db, target_user_id)
    updates = request.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = normalize_email(str(updates["email"]))
        if _email_exists(db, updates["email"], exclude_user_id=target_user_id):
            raise AdminUserConflictError(EMAIL_CONFLICT)

    next_role = updates.get("role", user.role)
    next_active = updates.get("is_active", user.is_active)
    current_role = (user.role or "").strip().lower()

    if target_user_id == actor_user_id and user.is_active and not next_active:
        raise AdminUserConflictError(SELF_DEACTIVATION_CONFLICT)
    if target_user_id == actor_user_id and current_role == "admin" and next_role != "admin":
        raise AdminUserConflictError(SELF_DEMOTION_CONFLICT)

    removes_active_admin = (
        user.is_active
        and current_role == "admin"
        and (not next_active or next_role != "admin")
    )
    try:
        if removes_active_admin and len(_lock_active_admin_ids(db)) <= 1:
            raise AdminUserConflictError(FINAL_ADMIN_CONFLICT)

        changed_fields = [name for name, value in updates.items() if getattr(user, name) != value]
        old_role = user.role
        old_active = user.is_active
        for name, value in updates.items():
            setattr(user, name, value)
        if changed_fields:
            user.updated_at = datetime.now(timezone.utc)
            db.add(user)
            _add_audit(
                db,
                actor_user_id=actor_user_id,
                action="user.updated",
                target_user_id=target_user_id,
                metadata={"changed_fields": sorted(changed_fields)},
            )
            if "role" in changed_fields:
                _add_audit(
                    db,
                    actor_user_id=actor_user_id,
                    action="user.role_changed",
                    target_user_id=target_user_id,
                    metadata={"old_role": old_role, "new_role": user.role},
                )
            if "is_active" in changed_fields:
                _add_audit(
                    db,
                    actor_user_id=actor_user_id,
                    action="user.activated" if user.is_active else "user.deactivated",
                    target_user_id=target_user_id,
                    metadata={"old_is_active": old_active, "new_is_active": user.is_active},
                )
        db.commit()
        db.refresh(user)
        return user
    except AdminUserConflictError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise AdminUserConflictError(PERSISTENCE_CONFLICT) from None
    except Exception:
        db.rollback()
        raise


def reset_password(
    db: Session,
    *,
    actor_user_id: int,
    target_user_id: int,
    new_password: str,
) -> int:
    user = _get_user(db, target_user_id)
    try:
        user.password_hash = hash_password(new_password)
        user.updated_at = datetime.now(timezone.utc)
        db.add(user)
        _add_audit(
            db,
            actor_user_id=actor_user_id,
            action="user.password_reset",
            target_user_id=target_user_id,
            metadata={"credential_changed": True},
        )
        db.commit()
        return target_user_id
    except Exception:
        db.rollback()
        raise


def _date_bounds(
    date_from: date | datetime | None,
    date_to: date | datetime | None,
) -> tuple[datetime | None, datetime | None]:
    start = (
        datetime.combine(date_from, time.min)
        if isinstance(date_from, date) and not isinstance(date_from, datetime)
        else date_from
    )
    end = (
        datetime.combine(date_to, time.max)
        if isinstance(date_to, date) and not isinstance(date_to, datetime)
        else date_to
    )
    return start, end


def validate_date_range(
    date_from: date | datetime | None,
    date_to: date | datetime | None,
) -> tuple[datetime | None, datetime | None]:
    start, end = _date_bounds(date_from, date_to)
    if start is not None and end is not None:
        comparable_start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        comparable_end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        if comparable_start > comparable_end:
            raise ValueError("date_from must not be later than date_to.")
    return start, end


def get_user_activity(
    db: Session,
    *,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    page: int,
    page_size: int,
    role: str | None,
    is_active: bool | None,
) -> dict[str, Any]:
    start, end = validate_date_range(date_from, date_to)
    join_conditions = [RetrievalRequest.user_id == User.user_id]
    if start is not None:
        join_conditions.append(RetrievalRequest.created_at >= start)
    if end is not None:
        join_conditions.append(RetrievalRequest.created_at <= end)
    filters = []
    if role is not None:
        filters.append(_role_expression() == role)
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))

    total = db.execute(select(func.count(User.user_id)).where(*filters)).scalar_one()
    questions_count = func.count(RetrievalRequest.retrieval_id).label("questions_count")
    statement = (
        select(
            User.user_id,
            User.full_name,
            User.email,
            User.role,
            User.is_active,
            questions_count,
            func.max(RetrievalRequest.created_at).label("last_question_at"),
        )
        .outerjoin(RetrievalRequest, and_(*join_conditions))
        .where(*filters)
        .group_by(User.user_id, User.full_name, User.email, User.role, User.is_active)
        .order_by(desc(questions_count), asc(User.user_id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [dict(row) for row in db.execute(statement).mappings().all()]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": ceil(total / page_size) if total else 0,
        "date_from": date_from,
        "date_to": date_to,
    }


def get_question_analytics(
    db: Session,
    *,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    limit: int,
    user_id: int | None,
    role: str | None,
    minimum_count: int,
) -> dict[str, Any]:
    start, end = validate_date_range(date_from, date_to)
    normalized = func.lower(
        func.regexp_replace(func.btrim(RetrievalRequest.query_text), r"\s+", " ", "g")
    ).label("normalized_question")
    filters = [
        RetrievalRequest.query_text.is_not(None),
        func.btrim(RetrievalRequest.query_text) != "",
    ]
    if start is not None:
        filters.append(RetrievalRequest.created_at >= start)
    if end is not None:
        filters.append(RetrievalRequest.created_at <= end)
    if user_id is not None:
        filters.append(RetrievalRequest.user_id == user_id)
    if role is not None:
        filters.append(_role_expression() == role)

    grouped = (
        select(
            normalized,
            func.min(func.btrim(RetrievalRequest.query_text)).label("question"),
            func.count(RetrievalRequest.retrieval_id).label("question_count"),
            func.count(func.distinct(RetrievalRequest.user_id)).label("unique_users"),
            func.max(RetrievalRequest.created_at).label("last_asked_at"),
            func.min(RetrievalRequest.user_id).label("example_user_id"),
        )
        .join(User, User.user_id == RetrievalRequest.user_id)
        .where(*filters)
        .group_by(normalized)
        .having(func.count(RetrievalRequest.retrieval_id) >= minimum_count)
        .subquery()
    )
    example = aliased(User)
    statement = (
        select(
            grouped.c.question,
            grouped.c.normalized_question,
            grouped.c.question_count,
            grouped.c.unique_users,
            grouped.c.last_asked_at,
            example.user_id.label("example_user_id"),
            example.full_name.label("example_user_name"),
        )
        .join(example, example.user_id == grouped.c.example_user_id)
        .order_by(desc(grouped.c.question_count), desc(grouped.c.last_asked_at), asc(grouped.c.normalized_question))
        .limit(limit)
    )
    items = []
    for row in db.execute(statement).mappings().all():
        items.append(
            {
                "question": row["question"],
                "normalized_question": row["normalized_question"],
                "count": row["question_count"],
                "unique_users": row["unique_users"],
                "last_asked_at": row["last_asked_at"],
                "example_user": {
                    "user_id": row["example_user_id"],
                    "full_name": row["example_user_name"],
                },
            }
        )
    return {
        "items": items,
        "date_from": date_from,
        "date_to": date_to,
        "normalization": "trimmed, whitespace-collapsed and case-insensitive",
    }
