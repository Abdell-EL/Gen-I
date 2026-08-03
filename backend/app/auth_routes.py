from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth_dependencies import require_authenticated_user
from app.auth_schemas import (
    ActivationCompletedResponse, ActivationInspectionResponse, ActivationTokenRequest,
    AuthUserResponse, ChangePasswordRequest, ChangePasswordResponse,
    CompleteActivationRequest, ForgotPasswordRequest, ForgotPasswordResponse,
    ResetPasswordCompletionRequest, ResetPasswordCompletionResponse,
    ResetPasswordTokenValidationRequest, ResetPasswordTokenValidationResponse,
    SignInRequest, SignInResponse,
)
from app.config import (
    AuthRateLimitSettings, AuthSettings, PasswordResetSettings,
    get_auth_rate_limit_settings, get_auth_settings, get_password_reset_settings,
)
from app.database import get_db
from app.models import User
from app.security import MAX_PASSWORD_BYTES, PasswordTooLongError, create_access_token
from app.services.auth_service import (
    InvalidCredentialsError, authenticate_user, normalize_email,
)
from app.services.auth_rate_limit_service import (
    RATE_LIMITED_MESSAGE, AuthRateLimiter, RateLimitDecision,
    client_host_from_request, get_auth_rate_limiter, log_auth_event,
)
from app.services.invitation_service import (
    InvalidActivationTokenError, complete_activation, inspect_activation_token,
)
from app.services.password_reset_delivery import (
    PasswordResetDeliveryProvider, get_password_reset_delivery_provider,
)
from app.services.password_change_service import (
    ChangePasswordAuthenticationError,
    ChangePasswordPersistenceError,
    IncorrectCurrentPasswordError,
    PasswordReuseError,
    change_own_password,
)
from app.services.password_reset_service import (
    FORGOT_PASSWORD_MESSAGE, RESET_PASSWORD_COMPLETED_MESSAGE,
    ConsumedPasswordResetTokenError, ExpiredPasswordResetTokenError,
    InvalidPasswordResetTokenError, PasswordResetEmptyPasswordError,
    PasswordResetPasswordMismatchError, PasswordResetPasswordReuseError,
    PasswordResetPersistenceError, complete_password_reset,
    inspect_password_reset_token, request_password_reset,
)


router = APIRouter(prefix="/auth", tags=["authentication"])


def password_reset_provider(
    settings: PasswordResetSettings = Depends(get_password_reset_settings),
) -> PasswordResetDeliveryProvider:
    return get_password_reset_delivery_provider(settings)


def auth_rate_limiter(
    settings: AuthRateLimitSettings = Depends(get_auth_rate_limit_settings),
) -> AuthRateLimiter:
    return get_auth_rate_limiter(settings)


def _rate_limited_exception(
    decision: RateLimitDecision,
    *,
    event: str,
    action: str,
) -> HTTPException:
    log_auth_event(event, action=action, decision=decision)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMITED_MESSAGE,
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


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
    http_request: Request,
    settings: AuthSettings = Depends(get_auth_settings),
    db: Session = Depends(get_db),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    normalized_email = normalize_email(str(request.email))
    client_host = client_host_from_request(http_request)
    limit_decision = limiter.reserve_signin(normalized_email, client_host)
    if not limit_decision.allowed:
        raise _rate_limited_exception(
            limit_decision,
            event="auth_rate_limited",
            action="signin",
        )

    try:
        user = authenticate_user(
            db,
            email=normalized_email,
            password=request.password,
        )
    except InvalidCredentialsError as error:
        log_auth_event(
            "auth_signin_failed",
            action="signin",
            decision=limit_decision,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    limiter.clear_signin_account(normalized_email, client_host)
    log_auth_event(
        "auth_signin_succeeded",
        action="signin",
        decision=limit_decision,
        actor_user_id=user.user_id,
    )

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
def validate_activation(
    request: ActivationTokenRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    limit_decision = limiter.reserve_activation_validation(
        request.token,
        client_host_from_request(http_request),
    )
    if not limit_decision.allowed:
        raise _rate_limited_exception(
            limit_decision,
            event="activation_rate_limited",
            action="activation_validate",
        )

    if not 32 <= len(request.token) <= 512:
        raise HTTPException(status_code=422, detail="Invalid activation request.")
    try:
        token = inspect_activation_token(db, request.token)
    except InvalidActivationTokenError as error:
        raise _activation_error(error) from None
    return ActivationInspectionResponse(expires_at=token.expires_at.isoformat())


@router.post("/activation/complete", response_model=ActivationCompletedResponse)
def activate_account(
    request: CompleteActivationRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    limit_decision = limiter.reserve_activation_completion(
        request.token,
        client_host_from_request(http_request),
    )
    if not limit_decision.allowed:
        raise _rate_limited_exception(
            limit_decision,
            event="activation_rate_limited",
            action="activation_complete",
        )

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


@router.post(
    "/password/forgot",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: PasswordResetSettings = Depends(get_password_reset_settings),
    provider: PasswordResetDeliveryProvider = Depends(password_reset_provider),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    limit_decision = limiter.reserve_forgot_password(
        normalize_email(str(request.email)),
        client_host_from_request(http_request),
    )
    if not limit_decision.allowed:
        response.headers["Retry-After"] = str(limit_decision.retry_after_seconds)
        log_auth_event(
            "password_reset_rate_limited",
            action="password_forgot",
            decision=limit_decision,
        )
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE, reset_url=None)

    try:
        result = request_password_reset(
            db,
            email=str(request.email),
            provider=provider,
            settings=settings,
        )
    except PasswordResetPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset request failed.",
        ) from error
    return ForgotPasswordResponse(
        message=FORGOT_PASSWORD_MESSAGE,
        reset_url=result.reset_url,
    )


def _reset_token_error(error: InvalidPasswordResetTokenError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "message": "Password reset link is not valid.",
            "code": error.code,
        },
    )


@router.post(
    "/password/reset/validate",
    response_model=ResetPasswordTokenValidationResponse,
)
def validate_password_reset_token(
    request: ResetPasswordTokenValidationRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    limit_decision = limiter.reserve_reset_validation(
        request.token,
        client_host_from_request(http_request),
    )
    if not limit_decision.allowed:
        raise _rate_limited_exception(
            limit_decision,
            event="password_reset_rate_limited",
            action="password_reset_validate",
        )

    try:
        token = inspect_password_reset_token(db, request.token)
    except InvalidPasswordResetTokenError as error:
        raise _reset_token_error(error) from None
    except PasswordResetPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset validation failed.",
        ) from error
    return ResetPasswordTokenValidationResponse(expires_at=token.expires_at)


@router.post(
    "/password/reset/complete",
    response_model=ResetPasswordCompletionResponse,
)
def complete_password_reset_route(
    request: ResetPasswordCompletionRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    limiter: AuthRateLimiter = Depends(auth_rate_limiter),
):
    limit_decision = limiter.reserve_reset_completion(
        request.token,
        client_host_from_request(http_request),
    )
    if not limit_decision.allowed:
        raise _rate_limited_exception(
            limit_decision,
            event="password_reset_rate_limited",
            action="password_reset_complete",
        )

    try:
        complete_password_reset(
            db,
            raw_token=request.token,
            password=request.password,
            password_confirmation=request.password_confirmation,
        )
    except InvalidPasswordResetTokenError as error:
        raise _reset_token_error(error) from None
    except PasswordResetPasswordMismatchError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password confirmation does not match.",
        ) from error
    except PasswordResetEmptyPasswordError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password must not be empty.",
        ) from error
    except PasswordResetPasswordReuseError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must be different from current password.",
        ) from error
    except PasswordTooLongError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except PasswordResetPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset completion failed.",
        ) from error
    return ResetPasswordCompletionResponse(
        message=RESET_PASSWORD_COMPLETED_MESSAGE,
        reauthentication_required=True,
    )


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
