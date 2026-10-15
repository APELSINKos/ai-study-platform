import logging
import sys
from typing import Final

import structlog
from structlog.typing import Processor

from app.core.config import LogFormat, LogLevel

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
# httpx2 logs every model request at INFO; pypdf warns about each defect it repairs in a file.
_QUIET_LOGGER_LEVELS: Final = {"httpx2": logging.WARNING, "pypdf": logging.ERROR}


def configure_logging(level: LogLevel, log_format: LogFormat) -> None:
    """Send structlog and standard-library logs through one stdout handler and format."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    render_processors: list[Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta
    ]
    if log_format == "json":
        render_processors += [
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
            ),
            structlog.processors.JSONRenderer(),
        ]
    else:
        render_processors.append(structlog.dev.ConsoleRenderer())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors, processors=render_processors
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(logging.NOTSET)

    # Propagated records skip the root's level check, so never set these below it.
    for name, quiet_level in _QUIET_LOGGER_LEVELS.items():
        logging.getLogger(name).setLevel(max(quiet_level, root.level))

    # RequestContextMiddleware writes the access log with the request id attached.
    logging.getLogger("uvicorn.access").disabled = True
