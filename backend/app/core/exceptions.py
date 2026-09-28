from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Final

from app.schemas.errors import ErrorDetail

_BEARER_CHALLENGE: Final = {"WWW-Authenticate": "Bearer"}


class AppError(Exception):
    """An error whose code and message are safe to show to API clients."""

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Sequence[ErrorDetail] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = list(details)
        self.headers = dict(headers) if headers else None
        super().__init__(self.message)


class AuthenticationError(AppError):
    """Always carries the bearer challenge header, unless the caller supplies its own."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "not_authenticated"
    message = "Authentication is required."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Sequence[ErrorDetail] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details, headers=headers or _BEARER_CHALLENGE)


class PermissionDeniedError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "permission_denied"
    message = "You do not have access to this resource."


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class RateLimitedError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many attempts. Try again later."
