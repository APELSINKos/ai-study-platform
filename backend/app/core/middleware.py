import re
import time
import uuid
from http import HTTPStatus
from typing import Final

import structlog
from fastapi.routing import iter_route_contexts
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import observe_http_request
from app.core.request_context import request_id_ctx
from app.core.timing import to_ms
from app.schemas.errors import ErrorBody, ErrorResponse

REQUEST_ID_HEADER: Final = "X-Request-ID"
INTERNAL_ERROR_CODE: Final = "internal_error"
UNMATCHED_ROUTE: Final = "unmatched"
_VALID_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._-]{8,64}")

logger = structlog.get_logger(__name__)


class RequestContextMiddleware:
    """Gives every HTTP request an id, logs and measures it, and turns crashes into JSON 500s."""

    def __init__(self, app: ASGIApp, quiet_paths: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.quiet_paths = quiet_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response_started = False
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("unhandled_exception", method=scope["method"], path=scope["path"])
            if response_started:
                raise
            await _internal_error(request_id)(scope, receive, send_with_request_id)
        finally:
            duration = time.perf_counter() - started
            route = route_template(scope)
            observe_http_request(scope["method"], route, status_code, duration)
            log = logger.debug if scope["path"] in self.quiet_paths else logger.info
            log(
                "request_finished",
                method=scope["method"],
                path=scope["path"],
                route=route,
                status=status_code,
                duration_ms=to_ms(duration),
                **_user_id_field(scope),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_ctx.reset(token)


def _user_id_field(scope: Scope) -> dict[str, str]:
    """The authenticated user's id, if `get_current_user` set one on this request."""
    state = scope.get("state")
    user_id = state.get("user_id") if isinstance(state, dict) else None
    return {"user_id": user_id} if isinstance(user_id, str) else {}


def route_template(scope: Scope) -> str:
    """Path template of the matched route, prefixes included; ids in URLs never become labels."""
    # scope["route"] alone omits prefixes from nested include_router() calls; FastAPI's
    # own "effective route context" carries the fully prefixed template instead.
    fastapi_scope = scope.get("fastapi")
    effective_route = (
        fastapi_scope.get("effective_route_context") if isinstance(fastapi_scope, dict) else None
    )
    path_format = getattr(effective_route, "path_format", None)
    if not isinstance(path_format, str):
        path_format = getattr(scope.get("route"), "path_format", None)
    if not isinstance(path_format, str):
        path_format = _plain_route_path_format(scope)
    return path_format if isinstance(path_format, str) else UNMATCHED_ROUTE


def _plain_route_path_format(scope: Scope) -> str | None:
    """Templates a request that no route recorded itself on.

    FastAPI adds the docs routes (/docs, /redoc, /openapi.json, ...) as plain Starlette
    routes, which unlike APIRoute never record themselves on scope["route"], and a request
    the body limiter refuses never reaches the router at all. Re-matching against the app's
    own routes, those of included routers too, is the only reliable way to recover their
    template.
    """
    router = scope.get("router") or getattr(scope.get("app"), "router", None)
    for route in iter_route_contexts(getattr(router, "routes", [])):
        match, _ = route.matches(scope)
        if match != Match.NONE and isinstance(route.path_format, str):
            return route.path_format
    return None


def _resolve_request_id(incoming: str | None) -> str:
    if incoming is not None and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def _internal_error(request_id: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=INTERNAL_ERROR_CODE, message="Internal server error.", request_id=request_id
        )
    )
    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content=body.model_dump(mode="json")
    )
