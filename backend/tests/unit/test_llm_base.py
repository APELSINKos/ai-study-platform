from typing import Final, get_args

import pytest

from app.core.exceptions import AppError
from app.llm.base import (
    ProviderError,
    ProviderRequestError,
    ProviderRequestErrorCode,
    ProviderUnavailableError,
)
from app.models.document import DOCUMENT_ERROR_CODES

REQUEST_ERROR_CODES: Final = get_args(ProviderRequestErrorCode.__value__)


def test_an_unavailable_provider_is_a_transient_ai_unavailable_error() -> None:
    error = ProviderUnavailableError("The endpoint did not answer.", retry_after_seconds=12.5)

    assert isinstance(error, ProviderError)
    assert error.code == "ai_unavailable"
    assert error.transient
    assert error.retry_after_seconds == 12.5
    assert str(error) == error.message == "The endpoint did not answer."


def test_an_unavailable_provider_may_give_no_retry_time() -> None:
    assert ProviderUnavailableError("Timed out.").retry_after_seconds is None


@pytest.mark.parametrize("code", REQUEST_ERROR_CODES)
def test_a_rejected_request_is_permanent(code: ProviderRequestErrorCode) -> None:
    error = ProviderRequestError("The model refused.", code=code)

    assert isinstance(error, ProviderError)
    assert error.code == code
    assert not error.transient
    assert error.retry_after_seconds is None


def test_every_code_a_provider_error_can_carry_is_a_document_error_code() -> None:
    codes = {ProviderUnavailableError("Timed out.").code, *REQUEST_ERROR_CODES}

    assert codes == {
        "ai_unavailable",
        "ai_rejected",
        "ai_quota_exceeded",
        "ai_invalid_output",
        "embedding_dimension_mismatch",
    }
    assert codes <= set(DOCUMENT_ERROR_CODES)


def test_provider_errors_are_not_api_errors() -> None:
    assert not issubclass(ProviderError, AppError)
