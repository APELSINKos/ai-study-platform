import uuid
from queue import Empty
from typing import Any, Final

import pytest
from celery import Celery
from kombu.exceptions import OperationalError
from kombu.message import Message

from app.core.request_context import request_id_ctx
from app.documents.queue import CeleryDocumentQueue, QueueUnavailableError
from app.workers.celery_app import PROCESS_DOCUMENT_TASK_NAME

_DOCUMENT_ID: Final = uuid.UUID("c41d9e07-6a2b-4f85-b3d1-8e7a5f0c2b64")
_REQUEST_ID: Final = "upload-request-0001"


@pytest.fixture
def memory_app() -> Celery:
    app = Celery("document-queue-tests", broker="memory://")
    # The in-memory broker is shared by every app in the process, so each test gets its
    # own queue.
    app.conf.task_default_queue = f"documents-{uuid.uuid4().hex}"
    return app


def _published(app: Celery) -> list[Message]:
    messages: list[Message] = []
    with app.connection_for_read() as connection:
        queue = connection.SimpleQueue(app.conf.task_default_queue)
        try:
            while True:
                message = queue.get(block=False)
                message.ack()
                messages.append(message)
        except Empty:
            pass
        finally:
            queue.close()
    return messages


def test_a_document_is_published_as_a_processing_task_with_its_id(memory_app: Celery) -> None:
    CeleryDocumentQueue(memory_app).enqueue(_DOCUMENT_ID)

    [message] = _published(memory_app)
    assert message.headers["task"] == PROCESS_DOCUMENT_TASK_NAME == "documents.process"
    args, kwargs, _ = message.decode()
    assert args == [str(_DOCUMENT_ID)]
    assert kwargs == {}


def test_the_message_carries_the_request_id_of_the_upload(memory_app: Celery) -> None:
    token = request_id_ctx.set(_REQUEST_ID)
    try:
        CeleryDocumentQueue(memory_app).enqueue(_DOCUMENT_ID)
    finally:
        request_id_ctx.reset(token)

    [message] = _published(memory_app)
    assert message.headers["request_id"] == _REQUEST_ID


def test_a_broker_that_cannot_take_the_message_is_reported_as_unavailable(
    memory_app: Celery, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(memory_app, "send_task", refuse)

    with pytest.raises(QueueUnavailableError) as exc_info:
        CeleryDocumentQueue(memory_app).enqueue(_DOCUMENT_ID)

    assert isinstance(exc_info.value.__cause__, OperationalError)
