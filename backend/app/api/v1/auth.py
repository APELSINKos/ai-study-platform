from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from redis import Redis

from app.api.cookies import REFRESH_COOKIE_NAME, clear_session_cookies, set_session_cookies
from app.api.deps import (
    AuthServiceDep,
    CurrentUser,
    RedisClient,
    SettingsDep,
    client_ip,
    verify_csrf,
)
from app.api.errors import error_response
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, SessionOut, TokenOut, UserOut
from app.schemas.errors import ErrorResponse
from app.schemas.text import has_surrogate
from app.services.auth import IssuedSession, invalid_credentials, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])

_MINUTE_SECONDS: Final = 60
_HOUR_SECONDS: Final = 3600
_REGISTER_RATE_LIMIT_SCOPE: Final = "auth_register_ip"
_LOGIN_IP_RATE_LIMIT_SCOPE: Final = "auth_login_ip"
_LOGIN_IP_EMAIL_RATE_LIMIT_SCOPE: Final = "auth_login_ip_email"
_LOGIN_EMAIL_RATE_LIMIT_SCOPE: Final = "auth_login_email"


def _session_out(user: User, issued: IssuedSession, now: datetime) -> SessionOut:
    expires_in = max(0, int((issued.access_token.expires_at - now).total_seconds()))
    return SessionOut(
        user=UserOut.model_validate(user),
        access_token=issued.access_token.value,
        expires_in=expires_in,
    )


def _enforce_login_rate_limits(redis: Redis, settings: Settings, *, ip: str, email: str) -> None:
    """Per-IP, per-IP-and-email and per-email limits, checked before password verification.

    The per-email limit is the only one that does not depend on the client address: it
    is what still stops password guessing when every request appears to come from the
    same IP (see the "Authentication" section of the README).
    """
    normalized_email = normalize_email(email)
    enforce_rate_limit(
        redis,
        RateLimit(
            _LOGIN_IP_RATE_LIMIT_SCOPE, settings.login_attempts_per_ip_per_minute, _MINUTE_SECONDS
        ),
        rate_limit_key(ip),
    )
    enforce_rate_limit(
        redis,
        RateLimit(
            _LOGIN_IP_EMAIL_RATE_LIMIT_SCOPE, settings.login_attempts_per_minute, _MINUTE_SECONDS
        ),
        rate_limit_key(ip, normalized_email),
    )
    enforce_rate_limit(
        redis,
        RateLimit(
            _LOGIN_EMAIL_RATE_LIMIT_SCOPE, settings.login_attempts_per_email_per_hour, _HOUR_SECONDS
        ),
        rate_limit_key(normalized_email),
    )


@router.post(
    "/register",
    status_code=HTTPStatus.CREATED,
    summary="Create an account and start a session",
    responses={
        HTTPStatus.CONFLICT: {"model": ErrorResponse},
        HTTPStatus.TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
def register(  # noqa: PLR0913, PLR0917 -- FastAPI dependency injection, not real complexity
    payload: RegisterRequest,
    request: Request,
    response: Response,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
) -> SessionOut:
    rule = RateLimit(_REGISTER_RATE_LIMIT_SCOPE, settings.registrations_per_hour, _HOUR_SECONDS)
    enforce_rate_limit(redis, rule, rate_limit_key(client_ip(request)))
    user = auth_service.register(
        email=payload.email, password=payload.password, display_name=payload.display_name
    )
    issued = auth_service.start_session(user, user_agent=request.headers.get("user-agent"))
    now = utcnow()
    set_session_cookies(response, issued, settings, now)
    return _session_out(user, issued, now)


@router.post(
    "/login",
    summary="Authenticate with email and password and start a session",
    responses={
        HTTPStatus.UNAUTHORIZED: {"model": ErrorResponse},
        HTTPStatus.TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
def login(  # noqa: PLR0913, PLR0917 -- FastAPI dependency injection, not real complexity
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
) -> SessionOut:
    _enforce_login_rate_limits(redis, settings, ip=client_ip(request), email=payload.email)
    user = auth_service.authenticate(email=payload.email, password=payload.password)
    issued = auth_service.start_session(user, user_agent=request.headers.get("user-agent"))
    now = utcnow()
    set_session_cookies(response, issued, settings, now)
    return _session_out(user, issued, now)


@router.post(
    "/token",
    summary="OAuth2-compatible password login, used by Swagger's Authorize button",
    responses={
        HTTPStatus.UNAUTHORIZED: {"model": ErrorResponse},
        HTTPStatus.TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
) -> TokenOut:
    # No account's email or password holds a surrogate, and one could not even be hashed
    # into a rate limit key.
    if has_surrogate(form.username) or has_surrogate(form.password):
        raise invalid_credentials()
    _enforce_login_rate_limits(redis, settings, ip=client_ip(request), email=form.username)
    user = auth_service.authenticate(email=form.username, password=form.password)
    access_token = auth_service.issue_access_token(user)
    return TokenOut(access_token=access_token.value)


@router.post(
    "/refresh",
    response_model=SessionOut,
    summary="Rotate the refresh cookie and issue a new session",
    responses={
        HTTPStatus.UNAUTHORIZED: {"model": ErrorResponse},
        HTTPStatus.FORBIDDEN: {"model": ErrorResponse},
    },
)
def refresh(
    request: Request, response: Response, auth_service: AuthServiceDep, settings: SettingsDep
) -> SessionOut | JSONResponse:
    verify_csrf(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME, "")
    try:
        user, issued = auth_service.rotate_session(
            refresh_token, user_agent=request.headers.get("user-agent")
        )
    except AuthenticationError as exc:
        failure = error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)
        clear_session_cookies(failure, settings)
        return failure
    now = utcnow()
    set_session_cookies(response, issued, settings, now)
    return _session_out(user, issued, now)


@router.post("/logout", status_code=HTTPStatus.NO_CONTENT, summary="End the current session")
def logout(
    request: Request, response: Response, auth_service: AuthServiceDep, settings: SettingsDep
) -> None:
    """End the session tied to the refresh cookie, if any, and clear all session cookies.

    No CSRF check: a cross-site form POST here would at worst sign the user out, and
    the refresh cookie's SameSite=Strict attribute already keeps it out of cross-site
    requests in the first place.
    """
    auth_service.end_session(request.cookies.get(REFRESH_COOKIE_NAME))
    clear_session_cookies(response, settings)


@router.get(
    "/me",
    summary="Get the current user",
    responses={HTTPStatus.UNAUTHORIZED: {"model": ErrorResponse}},
)
def me(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)
