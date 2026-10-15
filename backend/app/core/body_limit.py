import re
from http import HTTPStatus
from typing import Final

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response
from app.core.config import MIB, Settings
from app.core.exceptions import AppError, PayloadTooLargeError
from app.core.request_auth import authenticate_request

MAX_REQUEST_BODY_BYTES: Final = MIB
# Room for the multipart boundary and part headers around an uploaded file.
MULTIPART_OVERHEAD_BYTES: Final = 64 * 1024
_UPLOAD_METHOD: Final = "POST"


class RequestBodyLimitMiddleware:
    """Caps every request body at MAX_REQUEST_BODY_BYTES, the upload route's at the upload limit.

    A body declaring a length over its cap is refused before any of it is read; one sent
    without a length is cut off once it passes the cap. On the upload route the caller is
    authenticated first, so an anonymous client never gets the server to spool a file.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings, upload_path: re.Pattern[str]) -> None:
        self.app = app
        self.settings = settings
        self.upload_path = upload_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = MAX_REQUEST_BODY_BYTES
        if scope["method"] == _UPLOAD_METHOD and self.upload_path.fullmatch(scope["path"]):
            connection = HTTPConnection(scope)
            try:
                authenticate_request(
                    scope["method"],
                    connection.headers,
                    connection.cookies,
                    secret=self.settings.secret_key.get_secret_value(),
                )
            except AppError as exc:
                # Sent rather than raised: an exception from here would bypass the app's
                # exception handlers and reach the client as a 500 without CORS headers.
                await _send_error(exc, scope, receive, send)
                return
            limit = self.settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES

        declared_length = _declared_length(scope)
        if declared_length is not None and declared_length > limit:
            await _send_error(PayloadTooLargeError(), scope, receive, send)
            return
        await self.app(scope, _receive_within(limit, receive), send)


def _declared_length(scope: Scope) -> int | None:
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        # Treated as undeclared: the running count in _receive_within still applies.
        return None


def _receive_within(limit: int, receive: Receive) -> Receive:
    received = 0

    async def receive_within_limit() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                # Not an AppError: FastAPI re-raises an HTTPException met while it reads
                # the body, but turns any other exception there into a 400.
                raise HTTPException(HTTPStatus.CONTENT_TOO_LARGE, PayloadTooLargeError.message)
        return message

    return receive_within_limit


async def _send_error(error: AppError, scope: Scope, receive: Receive, send: Send) -> None:
    response = error_response(
        error.status_code, error.code, error.message, error.details, error.headers
    )
    await response(scope, receive, send)
