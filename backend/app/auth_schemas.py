from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AuthUserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool




class ActivationTokenRequest(BaseModel):
    token: str


class ActivationInspectionResponse(BaseModel):
    valid: Literal[True] = True
    expires_at: datetime


class CompleteActivationRequest(ActivationTokenRequest):
    password: str
    password_confirmation: str


class ActivationCompletedResponse(BaseModel):
    status: Literal["activated"] = "activated"
    user_id: int


class SignInResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse
