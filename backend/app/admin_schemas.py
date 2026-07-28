from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.security import MAX_PASSWORD_BYTES


UserRole = Literal["admin", "agent"]
SortField = Literal["created_at", "full_name", "email", "role"]
SortOrder = Literal["asc", "desc"]


def _validate_password(value: str) -> str:
    if not value:
        raise ValueError("Password must not be empty.")
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password exceeds the {MAX_PASSWORD_BYTES}-byte UTF-8 limit.")
    return value


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(validation_alias="user_id")
    full_name: str
    email: str
    role: str
    is_active: bool
    department_id: int | None
    created_at: datetime | None
    updated_at: datetime | None


class UserListResponse(BaseModel):
    items: list[AdminUserResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreateUserRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole = "agent"
    department_id: int | None = None
    is_active: bool = True

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Full name must not be empty.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    department_id: int | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Full name must not be empty.")
        return normalized

    @model_validator(mode="after")
    def reject_empty_or_null_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        non_nullable = {"full_name", "email", "role", "is_active"}
        if any(getattr(self, field) is None for field in self.model_fields_set & non_nullable):
            raise ValueError("Only department_id may be null.")
        return self


class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class PasswordResetResponse(BaseModel):
    status: Literal["password_reset"] = "password_reset"
    user_id: int


class UserActivityItem(BaseModel):
    user_id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    questions_count: int
    last_question_at: datetime | None


class UserActivityResponse(BaseModel):
    items: list[UserActivityItem]
    page: int
    page_size: int
    total: int
    pages: int
    date_from: date | datetime | None
    date_to: date | datetime | None


class ExampleUser(BaseModel):
    user_id: int
    full_name: str


class QuestionAnalyticsItem(BaseModel):
    question: str
    normalized_question: str
    count: int
    unique_users: int
    last_asked_at: datetime
    example_user: ExampleUser


class QuestionAnalyticsResponse(BaseModel):
    items: list[QuestionAnalyticsItem]
    date_from: date | datetime | None
    date_to: date | datetime | None
    normalization: str = "trimmed, whitespace-collapsed and case-insensitive"
