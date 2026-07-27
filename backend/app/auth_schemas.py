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


class SignInResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse
