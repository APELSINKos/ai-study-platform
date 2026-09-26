import secrets
from typing import Annotated

from fastapi import APIRouter, Header, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import SettingsDep
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, NotFoundError

router = APIRouter(include_in_schema=False)


@router.get("/metrics")
def metrics(
    settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> Response:
    _authorize_scrape(settings, authorization)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _authorize_scrape(settings: Settings, authorization: str | None) -> None:
    if settings.metrics_token is None:
        if settings.is_production:
            raise NotFoundError()
        return
    expected = f"Bearer {settings.metrics_token.get_secret_value()}"
    if authorization is None or not secrets.compare_digest(
        authorization.encode(), expected.encode()
    ):
        raise AuthenticationError(
            "A valid metrics token is required.", headers={"WWW-Authenticate": "Bearer"}
        )
