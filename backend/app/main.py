from typing import Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware

API_V1_PREFIX: Final = "/api/v1"
HEALTH_PATHS: Final = frozenset({f"{API_V1_PREFIX}/health/live", f"{API_V1_PREFIX}/health/ready"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(title=settings.app_name, version=__version__)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestContextMiddleware, quiet_paths=HEALTH_PATHS)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app
