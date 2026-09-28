from datetime import datetime
from typing import Final, Literal

from fastapi import Response

from app.core.config import Settings
from app.services.auth import IssuedSession

ACCESS_COOKIE_NAME: Final = "recall_access"
REFRESH_COOKIE_NAME: Final = "recall_refresh"
CSRF_COOKIE_NAME: Final = "recall_csrf"

ACCESS_COOKIE_PATH: Final = "/api"
REFRESH_COOKIE_PATH: Final = "/api/v1/auth"
CSRF_COOKIE_PATH: Final = "/"

CSRF_HEADER_NAME: Final = "X-CSRF-Token"

_ACCESS_SAMESITE: Final[Literal["lax"]] = "lax"
_REFRESH_SAMESITE: Final[Literal["strict"]] = "strict"
_CSRF_SAMESITE: Final[Literal["lax"]] = "lax"


def set_session_cookies(
    response: Response, issued: IssuedSession, settings: Settings, now: datetime
) -> None:
    """Set the access, refresh and CSRF cookies for a newly issued or rotated session."""
    secure = settings.secure_cookies
    access_max_age = max(0, int((issued.access_token.expires_at - now).total_seconds()))
    refresh_max_age = max(0, int((issued.refresh_expires_at - now).total_seconds()))
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        issued.access_token.value,
        max_age=access_max_age,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        samesite=_ACCESS_SAMESITE,
        secure=secure,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        issued.refresh_token,
        max_age=refresh_max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite=_REFRESH_SAMESITE,
        secure=secure,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        issued.csrf_token,
        max_age=refresh_max_age,
        path=CSRF_COOKIE_PATH,
        httponly=False,
        samesite=_CSRF_SAMESITE,
        secure=secure,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    """Delete the three session cookies, matching the attributes they were set with."""
    secure = settings.secure_cookies
    response.delete_cookie(
        ACCESS_COOKIE_NAME, path=ACCESS_COOKIE_PATH, samesite=_ACCESS_SAMESITE, secure=secure
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH, samesite=_REFRESH_SAMESITE, secure=secure
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path=CSRF_COOKIE_PATH, samesite=_CSRF_SAMESITE, secure=secure
    )
