from http import HTTPStatus

from fastapi import APIRouter

from app.api.v1 import auth, documents, health, workspaces
from app.schemas.errors import ErrorResponse

api_router = APIRouter(
    responses={
        HTTPStatus.UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "The request contains invalid data.",
        }
    }
)
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(documents.workspace_documents_router)
