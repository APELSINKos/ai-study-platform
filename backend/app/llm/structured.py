"""Asking a chat model for JSON that matches a Pydantic model, with one chance to repair it."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from openai import OpenAI
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from openai.types.shared_params import ResponseFormatJSONObject, ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from app.core.config import StructuredOutputMode
from app.documents.text import shorten
from app.llm.base import ProviderRequestError

# The first answer and one repaired answer.
STRUCTURED_OUTPUT_ATTEMPTS: Final = 2
REPAIR_PROBLEMS_MAX_CHARS: Final = 1000
REPAIR_NOTE: Final = (
    "An earlier answer to this request did not match the required JSON schema. "
    "Problems: {problems}. Reply with only a JSON object that fixes them."
)
_NOT_USER_TEXT_MESSAGE: Final = "The last message of a structured request must be the user's text."
_NO_ANSWER_MESSAGE: Final = "The model returned no answer."
_REFUSED_MESSAGE: Final = "The model refused to analyse the document."
_CUT_OFF_MESSAGE: Final = "The model's answer was cut off by the output token limit."
_INVALID_ANSWER_MESSAGE: Final = "The model's answer did not match the schema, even after a repair."


@dataclass(frozen=True, slots=True)
class ChatOptions:
    """Which chat model answers, how it is held to the schema and how long it may answer."""

    model: str
    structured_output: StructuredOutputMode
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class StructuredOutput[T: BaseModel]:
    """A validated answer and the tokens spent on it, repair included."""

    value: T
    prompt_tokens: int
    completion_tokens: int


def response_format(
    schema: type[BaseModel], mode: StructuredOutputMode
) -> ResponseFormatJSONSchema | ResponseFormatJSONObject:
    """The response_format that asks for JSON shaped by schema."""
    if mode == "json_object":
        # Only valid JSON is promised: the prompt names the fields and validation checks them.
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
            "strict": True,
        },
    }


def split_user_text(
    messages: Sequence[ChatCompletionMessageParam],
) -> tuple[list[ChatCompletionMessageParam], str]:
    """Messages that end with the user's text, split into the ones before it and the text.

    A structured request must end with that text, as a repeated request adds a note of what
    was wrong to it; other messages raise ValueError.
    """
    last = messages[-1] if messages else None
    user_text = None if last is None else last.get("content")
    if last is None or last["role"] != "user" or not isinstance(user_text, str):
        raise ValueError(_NOT_USER_TEXT_MESSAGE)
    return list(messages[:-1]), user_text


def complete_structured[T: BaseModel](
    client: OpenAI,
    options: ChatOptions,
    messages: Sequence[ChatCompletionMessageParam],
    user_text: str,
    schema: type[T],
) -> StructuredOutput[T]:
    """Ask for an answer that validates as schema; after a mismatch, ask once more.

    The request is the messages followed by the user's text, to which the repeated request
    adds a note of what was wrong. A refusal, a cut-off answer or a second mismatch raises
    ProviderRequestError (ai_invalid_output); errors of the API call itself propagate as the
    SDK raises them.
    """
    request: list[ChatCompletionMessageParam] = [*messages, {"role": "user", "content": user_text}]
    requested_format = response_format(schema, options.structured_output)
    prompt_tokens = completion_tokens = 0
    for _ in range(STRUCTURED_OUTPUT_ATTEMPTS):
        completion = client.chat.completions.create(
            model=options.model,
            messages=request,
            response_format=requested_format,
            max_completion_tokens=options.max_output_tokens,
        )
        content = _answer_text(completion)
        usage = completion.usage
        if isinstance(usage, CompletionUsage):
            prompt_tokens += _token_count(usage.prompt_tokens)
            completion_tokens += _token_count(usage.completion_tokens)
        try:
            value = schema.model_validate_json(content)
        except ValidationError as error:
            # Only the problems go back, not the rejected answer, whose text the document may
            # have steered. They join the user's turn, as some chat templates refuse two user
            # messages in a row.
            note = REPAIR_NOTE.format(problems=_problems(error))
            request = [*messages, {"role": "user", "content": f"{user_text}\n\n{note}"}]
            continue
        return StructuredOutput(
            value=value, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
    raise ProviderRequestError(_INVALID_ANSWER_MESSAGE, code="ai_invalid_output")


def _answer_text(completion: ChatCompletion) -> str:
    """The text of the first choice, or ProviderRequestError when there is nothing to use."""
    # The SDK does not validate an answer: a body that is not JSON reaches here as a plain
    # string, and a part of another shape as the server sent it.
    choices = completion.choices if isinstance(completion, ChatCompletion) else None
    choice = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(choice, Choice) or not isinstance(choice.message, ChatCompletionMessage):
        raise ProviderRequestError(_NO_ANSWER_MESSAGE, code="ai_invalid_output")
    message = choice.message
    if message.refusal or choice.finish_reason == "content_filter":
        raise ProviderRequestError(_REFUSED_MESSAGE, code="ai_invalid_output")
    if choice.finish_reason == "length":
        raise ProviderRequestError(_CUT_OFF_MESSAGE, code="ai_invalid_output")
    return message.content if isinstance(message.content, str) else ""


def _token_count(tokens: object) -> int:
    """A count from the usage report, or 0 when the server left it out or sent another type."""
    return tokens if isinstance(tokens, int) else 0


def _problems(error: ValidationError) -> str:
    """What was wrong, one "field: message" per problem, short enough to send back.

    A field that the schema does not have is reported without its name, which the model made
    up and so could carry text of its own.
    """
    problems: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        if location and item["type"] != "extra_forbidden":
            problems.append(f"{location}: {item['msg']}")
        else:
            problems.append(item["msg"])
    return shorten("; ".join(dict.fromkeys(problems)), REPAIR_PROBLEMS_MAX_CHARS)
