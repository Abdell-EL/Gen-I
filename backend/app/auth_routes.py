from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth_dependencies import require_authenticated_user
from app.auth_schemas import (
    ActivationCompletedResponse, ActivationInspectionResponse, ActivationTokenRequest,
    AuthUserResponse, ChangePasswordRequest, ChangePasswordResponse,
    CompleteActivationRequest, SignInRequest, SignInResponse,
)
from app.config import AuthSettings, get_auth_settings
from app.database import get_db
from app.models import User
from app.security import MAX_PASSWORD_BYTES, PasswordTooLongError, create_access_token
from app.services.auth_service import InvalidCredentialsError, authenticate_user
from app.services.invitation_service import (
    InvalidActivationTokenError, complete_activation, inspect_activation_token,
)
from app.services.password_change_service import (
    ChangePasswordAuthenticationError,
    ChangePasswordPersistenceError,
    IncorrectCurrentPasswordError,
    PasswordReuseError,
    change_own_password,
)


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
        version=int(getattr(user, "token_version", 0) or 0),
    )
    return SignInResponse(
        access_token=access_token,
        expires_in=settings.access_token_minutes * 60,
        user=serialize_user(user),
    )


def _activation_error(error: InvalidActivationTokenError) -> HTTPException:
    return HTTPException(status_code=400, detail={
        "message": "Activation link is not valid.",
        "code": error.code,
    })


@router.post("/activation/validate", response_model=ActivationInspectionResponse)
def validate_activation(request: ActivationTokenRequest, db: Session = Depends(get_db)):
    if not 32 <= len(request.token) <= 512:
        raise HTTPException(status_code=422, detail="Invalid activation request.")
    try:
        token = inspect_activation_token(db, request.token)
    except InvalidActivationTokenError as error:
        raise _activation_error(error) from None
    return ActivationInspectionResponse(expires_at=token.expires_at.isoformat())


@router.post("/activation/complete", response_model=ActivationCompletedResponse)
def activate_account(request: CompleteActivationRequest, db: Session = Depends(get_db)):
    if not 32 <= len(request.token) <= 512:
        raise HTTPException(status_code=422, detail="Invalid activation request.")
    if not request.password or request.password != request.password_confirmation:
        raise HTTPException(status_code=422, detail="Invalid activation request.")
    if len(request.password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(status_code=422, detail="Invalid activation request.")
    try:
        user = complete_activation(db, raw_token=request.token, password=request.password)
    except InvalidActivationTokenError as error:
        raise _activation_error(error) from None
    return ActivationCompletedResponse(user_id=user.user_id)


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: User = Depends(require_authenticated_user)):
    return serialize_user(current_user)


@router.post("/password/change", response_model=ChangePasswordResponse)
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    if not request.new_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must not be empty.",
        )
    if request.new_password != request.new_password_confirmation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password confirmation does not match.",
        )
    try:
        change_own_password(
            db,
            user_id=current_user.user_id,
            current_password=request.current_password,
            new_password=request.new_password,
        )
    except ChangePasswordAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except IncorrectCurrentPasswordError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        ) from error
    except PasswordReuseError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must be different from current password.",
        ) from error
    except PasswordTooLongError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ChangePasswordPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed.",
        ) from error
    return ChangePasswordResponse()
