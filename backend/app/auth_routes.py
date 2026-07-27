from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.auth_schemas import AuthUserResponse, SignInRequest, SignInResponse
from app.config import AuthSettings, get_auth_settings
from app.database import get_db
from app.models import User
from app.security import create_access_token
from app.services.auth_service import InvalidCredentialsError, authenticate_user


router = APIRouter(prefix="/auth", tags=["authentication"])


def serialize_user(user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.user_id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/signin", response_model=SignInResponse)
def signin(
    request: SignInRequest,
    settings: AuthSettings = Depends(get_auth_settings),
    db: Session = Depends(get_db),
):
    try:
        user = authenticate_user(
            db,
            email=str(request.email),
            password=request.password,
        )
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    access_token = create_access_token(
        signing_key=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        lifetime=timedelta(minutes=settings.access_token_minutes),
        subject=str(user.user_id),
    )
    return SignInResponse(
        access_token=access_token,
        expires_in=settings.access_token_minutes * 60,
        user=serialize_user(user),
    )


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)
