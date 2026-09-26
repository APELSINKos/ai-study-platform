import logging
import sys

import structlog
from structlog.typing import Processor

from app.core.config import LogFormat, LogLevel

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")


class _CurrentStdout:
    """Forwards to whatever sys.stdout is at write time.

    A plain StreamHandler(sys.stdout) freezes the stream object at setup time.
    Tools that swap sys.stdout afterwards (test runners capturing output,
    for instance) would then never see anything this handler writes.
    """

    def write(self, message: str) -> int:
        return sys.stdout.write(message)

    def flush(self) -> None:
        sys.stdout.flush()


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
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        render_processors.append(structlog.dev.ConsoleRenderer())

    handler = logging.StreamHandler(_CurrentStdout())
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

    # RequestContextMiddleware writes the access log with the request id attached.
    logging.getLogger("uvicorn.access").disabled = True
