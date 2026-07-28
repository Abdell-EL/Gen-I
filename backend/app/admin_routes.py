from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.admin_schemas import (
    AdminUserResponse,
    CreateUserRequest,
    OperationsSummaryResponse,
    OperationalSearchType,
    PasswordResetResponse,
    QuestionAnalyticsResponse,
    QuestionVolumeInterval,
    QuestionVolumeResponse,
    ResetPasswordRequest,
    SortField,
    SortOrder,
    UpdateUserRequest,
    UserActivityResponse,
    UserListResponse,
    UserRole,
)
from app.auth_dependencies import require_role
from app.database import get_db
from app.models import User
from app.services.admin_user_service import (
    AdminUserConflictError,
    AdminUserNotFoundError,
    create_user,
    get_question_analytics,
    get_user,
    get_user_activity,
    list_users,
    reset_password,
    update_user,
    validate_date_range,
)
from app.services.operations_analytics_service import (
    get_operations_summary,
    get_question_volume,
)


router = APIRouter(prefix="/admin", tags=["admin-control-plane"])
admin_only = require_role("admin")
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def _not_found(error: AdminUserNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _conflict(error: AdminUserConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _validate_dates(date_from, date_to) -> None:
    try:
        validate_date_range(date_from, date_to)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.get("/users", response_model=UserListResponse)
def admin_list_users(
    page: Page = 1,
    page_size: PageSize = 25,
    search: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    sort_by: SortField = "created_at",
    sort_order: SortOrder = "desc",
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return list_users(
        db,
        page=page,
        page_size=page_size,
        search=search,
        role=role,
        is_active=is_active,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def admin_get_user(
    user_id: int,
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        return get_user(db, user_id)
    except AdminUserNotFoundError as error:
        raise _not_found(error) from None


@router.post("/users", response_model=AdminUserResponse, status_code=201)
def admin_create_user(
    request: CreateUserRequest,
    current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        return create_user(db, actor_user_id=current_admin.user_id, request=request)
    except AdminUserConflictError as error:
        raise _conflict(error) from None


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def admin_update_user(
    user_id: int,
    request: UpdateUserRequest,
    current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        return update_user(
            db,
            actor_user_id=current_admin.user_id,
            target_user_id=user_id,
            request=request,
        )
    except AdminUserNotFoundError as error:
        raise _not_found(error) from None
    except AdminUserConflictError as error:
        raise _conflict(error) from None


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResponse)
def admin_reset_password(
    user_id: int,
    request: ResetPasswordRequest,
    current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    try:
        reset_user_id = reset_password(
            db,
            actor_user_id=current_admin.user_id,
            target_user_id=user_id,
            new_password=request.new_password,
        )
        return PasswordResetResponse(user_id=reset_user_id)
    except AdminUserNotFoundError as error:
        raise _not_found(error) from None


@router.get("/analytics/users", response_model=UserActivityResponse)
def admin_user_analytics(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    page: Page = 1,
    page_size: PageSize = 25,
    role: UserRole | None = None,
    is_active: bool | None = None,
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    _validate_dates(date_from, date_to)
    return get_user_activity(
        db,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
        role=role,
        is_active=is_active,
    )


@router.get("/analytics/questions", response_model=QuestionAnalyticsResponse)
def admin_question_analytics(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: int | None = Query(default=None, ge=1),
    role: UserRole | None = None,
    minimum_count: int = Query(default=1, ge=1, le=100000),
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    _validate_dates(date_from, date_to)
    return get_question_analytics(
        db,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        user_id=user_id,
        role=role,
        minimum_count=minimum_count,
    )


@router.get("/analytics/operations/summary", response_model=OperationsSummaryResponse)
def admin_operations_summary(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    user_id: int | None = Query(default=None, ge=1),
    role: UserRole | None = None,
    search_type: OperationalSearchType | None = None,
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    _validate_dates(date_from, date_to)
    return get_operations_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        role=role,
        search_type=search_type,
    )


@router.get("/analytics/operations/question-volume", response_model=QuestionVolumeResponse)
def admin_operations_question_volume(
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    interval: QuestionVolumeInterval = "day",
    user_id: int | None = Query(default=None, ge=1),
    role: UserRole | None = None,
    search_type: OperationalSearchType | None = None,
    _current_admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    _validate_dates(date_from, date_to)
    return get_question_volume(
        db,
        date_from=date_from,
        date_to=date_to,
        interval=interval,
        user_id=user_id,
        role=role,
        search_type=search_type,
    )
