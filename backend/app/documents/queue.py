import uuid
from typing import Final, Protocol

from celery import Celery
from kombu.exceptions import OperationalError

from app.workers.celery_app import PROCESS_DOCUMENT_TASK_NAME

_BROKER_UNAVAILABLE_MESSAGE: Final = "The message broker did not accept the processing request."


class QueueUnavailableError(Exception):
    """The processing request could not be handed to the broker."""


class DocumentQueue(Protocol):
    def enqueue(self, document_id: uuid.UUID) -> None: ...


class CeleryDocumentQueue:
    """Sends documents to the Celery worker by task name, without importing the task."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def enqueue(self, document_id: uuid.UUID) -> None:
        try:
            self._app.send_task(PROCESS_DOCUMENT_TASK_NAME, args=[str(document_id)])
        except OperationalError as exc:
            raise QueueUnavailableError(_BROKER_UNAVAILABLE_MESSAGE) from exc
