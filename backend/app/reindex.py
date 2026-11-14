"""Queue again the ready documents whose chunks another embedding model embedded.

Run in the worker container: python -m app.reindex [--dry-run]. Vectors of two models cannot
be compared, so a search leaves such documents out of its vector list until they have been
embedded with the current model. The command probes that model first and changes nothing if
it fails. Then it sends the documents back for processing one at a time, each by a
compare-and-set committed before the publish, so a run can be stopped and run again: the next
run queues the documents still ready. A stop during a publish leaves that one document in
uploaded with nothing queued; its owner's Retry recovers it 15 minutes later. The worker
processes the queued documents as it processes uploads.
"""

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.documents.queue import CeleryDocumentQueue, DocumentQueue, QueueUnavailableError
from app.llm.base import EmbeddingProvider, ProviderError
from app.llm.factory import build_embedding_provider, selected_models
from app.llm.probe import UNSENDABLE_KEY_MESSAGE, probe_embedding
from app.repositories.documents import DocumentRepository, ReindexCandidate
from app.workers.celery_app import celery_app

# Compose sets this variable for the worker; a host shell does not, and there the command
# would compare the stack's documents with the shell's models and publish to the stack's broker.
_STACK_VARIABLE: Final = "DATABASE_URL"
_OUTSIDE_THE_STACK_MESSAGE: Final = (
    "DATABASE_URL is not set, so this is not the worker container: run make reindex, or"
    " docker compose exec worker python -m app.reindex [--dry-run]. Nothing was changed."
)
# Stored on a document that the queue did not take; its owner's Retry recovers it.
_QUEUE_UNAVAILABLE_MESSAGE: Final = "The document could not be queued for re-indexing."
# What happens to the queued documents after a run; a dry run prints them too.
CAVEATS: Final = (
    "The command does not wait for processing: the worker re-indexes the queued documents in"
    " the background.",
    "Until then they count as active documents of their owners, whose uploads may be refused"
    " with too_many_active_documents.",
    "A document that fails while an AI provider is unavailable shows failed until its owner"
    " retries it.",
    "The per-user caps do not apply to this command itself.",
)


@dataclass(slots=True)
class _Summary:
    """What a run did with the documents it listed."""

    queued: int = 0
    reanalysed: int = 0
    skipped: int = 0
    failed_to_queue: int = 0


def main(  # noqa: PLR0913 -- every dependency is passed in, so a test can replace any
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingProvider | None = None,
    queue: DocumentQueue | None = None,
    session_factory: sessionmaker[Session] | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> int:
    """Run the command; the exit code is 1 when the probe failed or a document was not queued.

    Whatever is not passed in is what the worker itself uses. Settings are read from the
    environment only where DATABASE_URL is set, as in the worker container; elsewhere the
    command stops at once, with exit code 1.
    """
    dry_run = _dry_run(argv)
    if settings is None and _STACK_VARIABLE not in os.environ:
        print(_OUTSIDE_THE_STACK_MESSAGE)
        return 1
    settings = get_settings() if settings is None else settings
    # Built as the worker builds it, so that its name is the one the pipeline stores.
    embedder = build_embedding_provider(settings) if embedder is None else embedder
    if not _probe(embedder):
        return 1
    if session_factory is None:
        session_factory = get_session_factory(settings.database_url)
    chat_model = selected_models(settings).chat.model
    with session_factory.begin() as session:
        candidates = DocumentRepository(session).list_embedded_by_another_model(
            embedder.model_name, chat_model
        )
    if not candidates:
        print(f"Nothing to re-index: every ready document was embedded by {embedder.model_name}.")
        return 0
    _print_counts(candidates, chat_model, dry_run=dry_run)
    if dry_run:
        print("When run without --dry-run:")
        for caveat in CAVEATS:
            print(caveat)
        print("Dry run: nothing was changed.")
        return 0
    summary = _requeue(
        candidates,
        embedding_model=embedder.model_name,
        session_factory=session_factory,
        queue=CeleryDocumentQueue(celery_app) if queue is None else queue,
        clock=clock,
    )
    _print_summary(summary)
    return 0 if summary.failed_to_queue == 0 else 1


def _dry_run(argv: Sequence[str] | None) -> bool:
    """Whether the arguments ask for a dry run; --help and unknown arguments exit here."""
    parser = argparse.ArgumentParser(
        prog="python -m app.reindex",
        description="Queue the ready documents that another embedding model embedded for"
        " processing again, one at a time.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="count the documents and change nothing"
    )
    dry_run: bool = parser.parse_args(argv).dry_run
    return dry_run


def _probe(embedder: EmbeddingProvider) -> bool:
    """Whether the embedding model answers the probe; printed either way."""
    try:
        probe_embedding(embedder)
    except ProviderError as error:
        # The message is written from status codes, never from the API's own text.
        print(
            f"The embedding model {embedder.model_name} failed the probe: {error.code}"
            f" ({error.message})"
        )
        print("Nothing was changed.")
        return False
    except UnicodeEncodeError:
        print(
            f"The embedding model {embedder.model_name} failed the probe: {UNSENDABLE_KEY_MESSAGE}"
        )
        print("Nothing was changed.")
        return False
    print(f"The embedding model {embedder.model_name} answered the probe.")
    return True


def _print_counts(candidates: list[ReindexCandidate], chat_model: str, *, dry_run: bool) -> None:
    """How many documents the run sends back, and how many of them are analysed again."""
    verb = "would be" if dry_run else "will be"
    reanalysed = sum(1 for candidate in candidates if not candidate.reuses_analysis)
    print(f"Documents that {verb} re-indexed: {len(candidates)}")
    print(f"Documents that {verb} re-analysed too: {reanalysed}")
    print(
        f"A document is re-analysed when another chat model than {chat_model} analysed it, or"
        " its analysis is incomplete; with a live chat model, each re-analysis is a paid"
        " request."
    )


def _requeue(
    candidates: list[ReindexCandidate],
    *,
    embedding_model: str,
    session_factory: sessionmaker[Session],
    queue: DocumentQueue,
    clock: Callable[[], datetime],
) -> _Summary:
    """Send the documents back for processing one at a time, until the queue refuses one."""
    summary = _Summary()
    for position, candidate in enumerate(candidates):
        with session_factory.begin() as session:
            marked = DocumentRepository(session).mark_for_reindex(
                candidate.id, embedding_model, clock()
            )
        if not marked:
            # Deleted, queued again or re-indexed since it was listed.
            summary.skipped += 1
            continue
        try:
            queue.enqueue(candidate.id)
        except QueueUnavailableError:
            with session_factory.begin() as session:
                failed = DocumentRepository(session).mark_queue_unavailable(
                    candidate.id, candidate.attempts, _QUEUE_UNAVAILABLE_MESSAGE, clock()
                )
            summary.failed_to_queue += 1
            _print_refusal(candidate.id, failed=failed, left=len(candidates) - position - 1)
            # A broker that is down would fail every document after it in the same way.
            break
        summary.queued += 1
        if not candidate.reuses_analysis:
            summary.reanalysed += 1
    return summary


def _print_refusal(document_id: uuid.UUID, *, failed: bool, left: int) -> None:
    """Say what became of the document the queue did not take, and that the run stopped."""
    if failed:
        print(
            f"The queue did not take document {document_id}: it shows failed"
            " (queue_unavailable) until its owner retries it."
        )
    else:
        # A publish can fail after the broker took the message, as on upload.
        print(
            f"The queue reported an error for document {document_id}, which has moved on"
            " all the same: a worker claimed it, or its owner deleted it."
        )
    print(f"Stopped there. Documents left as they were, for a later run: {left}")


def _print_summary(summary: _Summary) -> None:
    """What the run did, then what happens to the queued documents."""
    print(f"Re-indexed (queued): {summary.queued}")
    print(f"Of them re-analysed: {summary.reanalysed}")
    print(f"Skipped because they changed meanwhile: {summary.skipped}")
    print(f"Failed to queue: {summary.failed_to_queue}")
    for caveat in CAVEATS:
        print(caveat)


if __name__ == "__main__":
    sys.exit(main())
