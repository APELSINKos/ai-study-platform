"""Check that the configured AI models answer: python -m app.check_ai [--chat].

Names the chat and embedding models in use and their providers, never a key or an address,
embeds one short sentence and, with --chat, has the chat model analyse it as a one-line
document. The API and the worker call no model when they start, so that a provider outage
cannot stop them: this command is the check to run instead. Run it in the worker container
(make check-ai): it checks the settings of the process it runs in.
"""

import argparse
import sys
from collections.abc import Callable, Sequence

from app.core.config import DEFAULT_OPENAI_BASE_URL, ProviderEndpoint, Settings, get_settings
from app.llm.base import EmbeddingProvider, LLMProvider, ProviderError
from app.llm.factory import (
    ModelChoice,
    build_embedding_provider,
    build_llm_provider,
    chat_endpoint,
    embedding_endpoint,
    selected_models,
)
from app.llm.probe import UNSENDABLE_KEY_MESSAGE, probe_chat, probe_embedding


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingProvider | None = None,
    llm: LLMProvider | None = None,
) -> int:
    """Name the models in use and probe them; the exit code is 1 when one of them fails.

    The providers not passed in are built from the settings, as the worker builds them.
    """
    chat = _wants_chat(argv)
    settings = get_settings() if settings is None else settings
    selection = selected_models(settings)
    print(f"Chat model: {_describe(selection.chat, chat_endpoint(settings))}")
    print(f"Embedding model: {_describe(selection.embedding, embedding_endpoint(settings))}")
    embedder = build_embedding_provider(settings) if embedder is None else embedder
    embedding_answered = _report("embedding", lambda: probe_embedding(embedder))
    if not chat:
        print(
            "The chat model was not exercised; run with --chat to send it one small analysis"
            " request."
        )
        return 0 if embedding_answered else 1
    # Probed even when the embeddings fail: the two often come from different vendors.
    llm = build_llm_provider(settings) if llm is None else llm
    chat_answered = _report("chat", lambda: probe_chat(llm))
    return 0 if embedding_answered and chat_answered else 1


def _report(kind: str, probe: Callable[[], float]) -> bool:
    """Run one probe and print how long the model took or how it failed; whether it answered."""
    try:
        latency = probe()
    except ProviderError as error:
        print(f"The {kind} model failed: {_failure(error)}")
        return False
    except UnicodeEncodeError:
        print(f"The {kind} model failed: {UNSENDABLE_KEY_MESSAGE}")
        return False
    print(f"The {kind} model answered in {latency} ms.")
    return True


def _wants_chat(argv: Sequence[str] | None) -> bool:
    """Whether the arguments ask for the chat model too; --help and unknown arguments exit here."""
    parser = argparse.ArgumentParser(
        prog="python -m app.check_ai",
        description="Name the configured AI models and check that they answer.",
    )
    parser.add_argument(
        "--chat", action="store_true", help="also send the chat model one small analysis request"
    )
    chat: bool = parser.parse_args(argv).chat
    return chat


def _describe(choice: ModelChoice, endpoint: ProviderEndpoint | None) -> str:
    """The model and its provider, and whether its requests go to OpenAI or elsewhere."""
    if endpoint is None:
        return f"{choice.model} (provider {choice.provider}, built in)"
    # A trailing slash names the same address.
    is_openai = endpoint.base_url.rstrip("/") == DEFAULT_OPENAI_BASE_URL
    where = "OpenAI" if is_openai else "custom endpoint"
    return f"{choice.model} (provider {choice.provider}, {where})"


def _failure(error: ProviderError) -> str:
    # The message is written from status codes, never from the API's own text.
    return f"{error.code} ({error.message})"


if __name__ == "__main__":
    sys.exit(main())
