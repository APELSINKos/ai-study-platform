import uuid
from http import HTTPStatus
from typing import Annotated, Final

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import CurrentUser, DocumentServiceDep, RedisClient, SettingsDep
from app.api.errors import error_responses
from app.api.pagination import PageParamsDep
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key
from app.models.document import DocumentStatus
from app.schemas.documents import DocumentOut, DocumentPage
from app.services.documents import DocumentView

_HOUR_SECONDS: Final = 3600
_UPLOAD_RATE_LIMIT_SCOPE: Final = "documents_upload_user"

# A router of its own: FastAPI adds a router's tags to every route on it, so routes on the
# workspaces router would be tagged as workspaces too.
workspace_documents_router = APIRouter(prefix="/workspaces", tags=["documents"])


def _document_out(view: DocumentView) -> DocumentOut:
    document = view.document
    return DocumentOut(
        id=document.id,
        workspace_id=document.workspace_id,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status,
        error_code=document.error_code,
        attempts=document.attempts,
        title=document.title,
        summary=document.summary,
        topics=document.topics,
        difficulty=document.difficulty,
        estimated_study_minutes=document.estimated_study_minutes,
        page_count=document.page_count,
        word_count=document.word_count,
        chunk_count=document.chunk_count,
        analysis_model=document.analysis_model,
        embedding_model=document.embedding_model,
        processing_ms=document.processing_ms,
        processing_started_at=document.processing_started_at,
        processed_at=document.processed_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        can_retry=view.can_retry,
    )


@workspace_documents_router.post(
    "/{workspace_id}/documents",
    status_code=HTTPStatus.ACCEPTED,
    summary="Upload a PDF, Markdown or text file to a workspace and queue it for processing",
    responses=error_responses(
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
        HTTPStatus.CONTENT_TOO_LARGE,
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        HTTPStatus.TOO_MANY_REQUESTS,
    ),
)
def upload_document(  # noqa: PLR0913, PLR0917 -- FastAPI dependency injection, not real complexity
    workspace_id: uuid.UUID,
    file: Annotated[
        UploadFile, File(description="A PDF, Markdown (.md) or plain text (.txt) file.")
    ],
    current_user: CurrentUser,
    service: DocumentServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
) -> DocumentOut:
    """The document starts as uploaded. When the queue cannot take it, it comes back failed
    with the error code queue_unavailable, and processing can be retried."""
    rule = RateLimit(_UPLOAD_RATE_LIMIT_SCOPE, settings.uploads_per_hour, _HOUR_SECONDS)
    enforce_rate_limit(redis, rule, rate_limit_key(str(current_user.id)))
    return _document_out(service.upload(user=current_user, workspace_id=workspace_id, upload=file))


@workspace_documents_router.get(
    "/{workspace_id}/documents",
    summary="List the documents of a workspace, the newest first",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND),
)
def list_documents(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    service: DocumentServiceDep,
    page: PageParamsDep,
    status: Annotated[
        DocumentStatus | None, Query(description="Only the documents in this status.")
    ] = None,
) -> DocumentPage:
    views, total = service.list_for_workspace(
        user=current_user,
        workspace_id=workspace_id,
        status=status,
        offset=page.offset,
        limit=page.limit,
    )
    return DocumentPage(
        items=[_document_out(view) for view in views],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
