from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.security import MAX_PASSWORD_BYTES


UserRole = Literal["admin", "agent"]
OperationalSearchType = Literal["search", "keyword_search", "chat"]
QuestionVolumeInterval = Literal["hour", "day", "week", "month"]
SortField = Literal["created_at", "full_name", "email", "role"]
SortOrder = Literal["asc", "desc"]
ScoreBasis = Literal["top_score", "all_results"]
ArticleSortField = Literal[
    "consultation_count", "unique_users", "last_consulted_at", "article_title"
]


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


class MostActiveUser(BaseModel):
    user_id: int
    full_name: str
    email: str
    questions_count: int


class MostAskedQuestion(BaseModel):
    question: str
    normalized_question: str
    questions_count: int


class MostConsultedArticle(BaseModel):
    article_title: str | None
    kb_code: str | None
    references_count: int


class OperationsSummaryResponse(BaseModel):
    date_from: date | datetime | None
    date_to: date | datetime | None
    total_questions: int
    unique_users: int
    active_users: int
    average_questions_per_active_user: float | None
    average_results_count: float | None
    average_top_score: float | None
    low_confidence_questions: int
    zero_result_questions: int
    most_active_user: MostActiveUser | None
    most_asked_question: MostAskedQuestion | None
    most_consulted_article: MostConsultedArticle | None


class QuestionVolumeItem(BaseModel):
    period_start: datetime
    questions_count: int
    unique_users: int


class QuestionVolumeResponse(BaseModel):
    interval: QuestionVolumeInterval
    items: list[QuestionVolumeItem]
    date_from: date | datetime | None
    date_to: date | datetime | None


class TrendingQuestionItem(BaseModel):
    question: str
    normalized_question: str
    current_count: int
    previous_count: int
    absolute_change: int
    percentage_change: float | None
    unique_users: int
    last_asked_at: datetime


class TrendingQuestionsResponse(BaseModel):
    items: list[TrendingQuestionItem]
    date_from: date | datetime | None
    date_to: date | datetime | None
    previous_period: bool
    normalization: str = "trimmed, whitespace-collapsed and case-insensitive"


class AnalyticsUser(BaseModel):
    id: int
    name: str
    email: str
    role: str


class LowConfidenceItem(BaseModel):
    retrieval_id: int
    query_text: str
    created_at: datetime
    user: AnalyticsUser
    search_type: OperationalSearchType | None
    results_count: int
    top_score: float | None
    average_score: float | None
    low_confidence_reason: Literal["zero_results", "top_score_below_threshold"]
    top_article_title: str | None
    top_kb_code: str | None


class LowConfidenceResponse(BaseModel):
    items: list[LowConfidenceItem]
    page: int
    page_size: int
    total: int
    pages: int
    threshold: float
    include_zero_results: bool


class ScoreBucket(BaseModel):
    lower_bound: float
    upper_bound: float
    count: int
    percentage: float


class ScoreDistributionResponse(BaseModel):
    bucket_size: float
    score_basis: ScoreBasis
    total: int
    buckets: list[ScoreBucket]


class ArticleAnalyticsItem(BaseModel):
    article_title: str | None
    kb_code: str | None
    consultation_count: int
    unique_requests: int
    unique_users: int
    average_score: float
    top_score: float
    last_consulted_at: datetime


class ArticleAnalyticsResponse(BaseModel):
    items: list[ArticleAnalyticsItem]
    page: int
    page_size: int
    total: int
    pages: int


class UnreferencedContentItem(BaseModel):
    source_document_id: int
    filename: str
    title: str | None
    kb_code: str | None
    current_version_chunk_count: int
    created_at: datetime | None
    last_referenced_at: datetime | None
    reference_count: int
    reference_scope: Literal["selected_period"] = "selected_period"


class UnreferencedContentResponse(BaseModel):
    items: list[UnreferencedContentItem]
    page: int
    page_size: int
    total: int
    pages: int
    date_from: date | datetime | None
    date_to: date | datetime | None
    scope_label: Literal["unreferenced_in_selected_period"] = "unreferenced_in_selected_period"


class RetrievalResultDetail(BaseModel):
    rank: int
    score: float
    chunk_external_id: str | None
    article_title: str | None
    kb_code: str | None
    section_title: str | None
    chunk_type: str | None
    priority: str | None


class RetrievalDrillDownResponse(BaseModel):
    retrieval_id: int
    query_text: str
    created_at: datetime
    top_k: int | None
    user: AnalyticsUser
    search_type: OperationalSearchType | None
    result_count: int
    session_id: int | None
    message_id: int | None
    results: list[RetrievalResultDetail]


class CacheStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    namespace: str
    version: str
    knowledge_generation: int | None
