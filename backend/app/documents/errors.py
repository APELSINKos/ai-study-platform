"""Errors that stop the processing of one document; the pipeline records them on it."""

from typing import Final

from app.models.document import DocumentErrorCode

TEXT_TOO_LONG_MESSAGE: Final = "The document has more text than can be processed."


class DocumentProcessingError(Exception):
    """A document that cannot be processed; code and message are stored on the document."""

    def __init__(self, code: DocumentErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Named after Celery's SoftTimeLimitExceeded, which it stands in for and is handled with.
# Unlike that one it is not an Exception, so code that swallows every Exception, as pypdf
# does while it repairs a file, lets it through.
class ProcessingDeadlineExceeded(BaseException):
    """A processing run reached its own deadline, set to end before the task time limit."""
