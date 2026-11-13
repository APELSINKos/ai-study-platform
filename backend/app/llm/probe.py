"""One small request to a configured model, to see that it answers before relying on it."""

import time
from typing import Final

from app.core.timing import to_ms
from app.llm.base import EmbeddingProvider

# Short and invented, so that a probe of a paid model costs next to nothing.
PROBE_SENTENCE: Final = "Spaced repetition brings each card back just before it would be forgotten."


def probe_embedding(embedder: EmbeddingProvider) -> float:
    """Embed the probe sentence; the milliseconds it took. Raises ProviderError on failure.

    The provider checks the vector it gets back itself: its size, its numbers and its norm.
    """
    started = time.perf_counter()
    embedder.embed([PROBE_SENTENCE])
    return to_ms(time.perf_counter() - started)
