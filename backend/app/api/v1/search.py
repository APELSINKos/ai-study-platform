import uuid
from http import HTTPStatus
from typing import Annotated, Final

from fastapi import APIRouter, Query
from pydantic import AfterValidator, StringConstraints

from app.api.deps import CurrentUser, RedisClient, SearchServiceDep, SettingsDep
from app.api.errors import error_responses
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key
from app.schemas.search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    QUERY_MAX_CHARS,
    SearchMode,
    SearchResults,
)
from app.schemas.text import reject_nul

_MINUTE_SECONDS: Final = 60
_SEARCH_RATE_LIMIT_SCOPE: Final = "search_user"

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    summary="Search the ready documents of a workspace for the passages that match a query",
    responses=error_responses(
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE,
    ),
)
def search(  # noqa: PLR0913, PLR0917 -- FastAPI dependency injection, not real complexity
    workspace_id: Annotated[uuid.UUID, Query(description="The workspace to search.")],
    q: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=QUERY_MAX_CHARS),
        AfterValidator(reject_nul),
        Query(
            description='What to look for. Among its words, quoted ones form a phrase, "or"'
            ' joins words of which one is enough, and a word after "-" must not occur. A query'
            " that excludes words is matched by its words alone, not by embeddings."
        ),
    ],
    current_user: CurrentUser,
    service: SearchServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="The most passages to return.")
    ] = DEFAULT_LIMIT,
    mode: Annotated[
        SearchMode,
        Query(
            description="hybrid: the query's words and similar embeddings together; vector:"
            " similar embeddings only; keyword: the words only."
        ),
    ] = "hybrid",
) -> SearchResults:
    """When the query cannot be embedded, a hybrid search looks for its words alone and
    answers with semantic_available false, and a vector search is a 503 with the error code
    search_unavailable."""
    rule = RateLimit(_SEARCH_RATE_LIMIT_SCOPE, settings.searches_per_minute, _MINUTE_SECONDS)
    enforce_rate_limit(redis, rule, rate_limit_key(str(current_user.id)))
    return service.search(
        user=current_user, workspace_id=workspace_id, text=q, mode=mode, limit=limit
    )
