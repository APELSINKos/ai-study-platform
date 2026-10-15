import uuid
from http import HTTPStatus

from fastapi import APIRouter

from app.api.deps import CurrentUser, WorkspaceServiceDep
from app.api.errors import error_responses
from app.api.pagination import PageParamsDep
from app.repositories.workspaces import WorkspaceWithStats
from app.schemas.workspaces import (
    WorkspaceCreateRequest,
    WorkspaceOut,
    WorkspacePage,
    WorkspaceStats,
    WorkspaceUpdateRequest,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _workspace_out(item: WorkspaceWithStats) -> WorkspaceOut:
    workspace = item.workspace
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        exam_date=workspace.exam_date,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        stats=WorkspaceStats.model_validate(item.stats),
    )


@router.get(
    "",
    summary="List your workspaces, the most recently updated first",
    responses=error_responses(HTTPStatus.UNAUTHORIZED),
)
def list_workspaces(
    current_user: CurrentUser, service: WorkspaceServiceDep, page: PageParamsDep
) -> WorkspacePage:
    items, total = service.list_for_user(user=current_user, offset=page.offset, limit=page.limit)
    return WorkspacePage(
        items=[_workspace_out(item) for item in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    summary="Create a workspace",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
)
def create_workspace(
    payload: WorkspaceCreateRequest, current_user: CurrentUser, service: WorkspaceServiceDep
) -> WorkspaceOut:
    return _workspace_out(service.create(user=current_user, request=payload))


@router.get(
    "/{workspace_id}",
    summary="Get a workspace with the statistics of its documents",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND),
)
def get_workspace(
    workspace_id: uuid.UUID, current_user: CurrentUser, service: WorkspaceServiceDep
) -> WorkspaceOut:
    return _workspace_out(service.get(user=current_user, workspace_id=workspace_id))


@router.patch(
    "/{workspace_id}",
    summary="Change a workspace's name, description or exam date",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
)
def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdateRequest,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceOut:
    return _workspace_out(
        service.update(user=current_user, workspace_id=workspace_id, changes=payload)
    )


@router.delete(
    "/{workspace_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete a workspace with its documents and their files",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
)
def delete_workspace(
    workspace_id: uuid.UUID, current_user: CurrentUser, service: WorkspaceServiceDep
) -> None:
    service.delete(user=current_user, workspace_id=workspace_id)
