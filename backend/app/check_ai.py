"""Check that the configured AI models answer: python -m app.check_ai [--chat].

Names the chat and embedding models in use and their providers, never a key or an address,
embeds one short sentence and, with --chat, has the chat model analyse it as a one-line
document. The API and the worker call no model when they start, so that a provider outage
cannot stop them: this command is the check to run instead.
"""

import argparse
import sys
from collections.abc import Sequence

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
from app.llm.probe import probe_chat, probe_embedding


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
    embedder = build_embedding_provider(settings) if embedder is None else embedder
    selection = selected_models(settings)
    print(f"Chat model: {_describe(selection.chat, chat_endpoint(settings))}")
    print(f"Embedding model: {_describe(selection.embedding, embedding_endpoint(settings))}")
    try:
        latency = probe_embedding(embedder)
    except ProviderError as error:
        print(f"The embedding model failed: {_failure(error)}")
        return 1
    print(f"The embedding model answered in {latency} ms.")
    if not chat:
        print(
            "The chat model was not exercised; run with --chat to send it one small analysis"
            " request."
        )
        return 0
    llm = build_llm_provider(settings) if llm is None else llm
    try:
        latency = probe_chat(llm)
    except ProviderError as error:
        print(f"The chat model failed: {_failure(error)}")
        return 1
    print(f"The chat model answered in {latency} ms.")
    return 0


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
