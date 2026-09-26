from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.request_context import get_request_id
from app.schemas.errors import ErrorBody, ErrorDetail, ErrorResponse

VALIDATION_ERROR_CODE: Final = "validation_error"
FALLBACK_HTTP_ERROR_CODE: Final = "http_error"
_INPUT_LOCATIONS: Final = frozenset({"body", "query", "path", "header", "cookie"})
_HTTP_ERROR_CODES: Final[dict[int, str]] = {
    HTTPStatus.BAD_REQUEST: "bad_request",
    HTTPStatus.UNAUTHORIZED: "not_authenticated",
    HTTPStatus.FORBIDDEN: "permission_denied",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
    HTTPStatus.CONTENT_TOO_LARGE: "payload_too_large",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Sequence[ErrorDetail] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, details=list(details), request_id=get_request_id()
        )
    )
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(field=_field_path(error["loc"]), message=error["msg"])
            for error in exc.errors()
        ]
        return error_response(
            HTTPStatus.UNPROCESSABLE_CONTENT,
            VALIDATION_ERROR_CODE,
            "The request contains invalid data.",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, FALLBACK_HTTP_ERROR_CODE)
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return error_response(exc.status_code, code, message, headers=exc.headers)


def _field_path(location: Sequence[object]) -> str | None:
    parts = [str(part) for part in location]
    if parts and parts[0] in _INPUT_LOCATIONS:
        parts = parts[1:]
    return ".".join(parts) or None
