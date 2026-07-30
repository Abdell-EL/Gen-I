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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirmation: str


class ChangePasswordResponse(BaseModel):
    message: Literal["Mot de passe modifié avec succès."] = "Mot de passe modifié avec succès."
    reauthentication_required: Literal[True] = True


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: Literal[
        "Si un compte éligible correspond à cette adresse, des instructions de réinitialisation seront envoyées."
    ] = "Si un compte éligible correspond à cette adresse, des instructions de réinitialisation seront envoyées."
    reset_url: str | None = None


class ResetPasswordTokenValidationRequest(BaseModel):
    token: str


class ResetPasswordTokenValidationResponse(BaseModel):
    valid: Literal[True] = True
    expires_at: datetime


class ResetPasswordCompletionRequest(BaseModel):
    token: str
    password: str
    password_confirmation: str


class ResetPasswordCompletionResponse(BaseModel):
    message: Literal["Mot de passe réinitialisé avec succès."] = "Mot de passe réinitialisé avec succès."
    reauthentication_required: Literal[True] = True
