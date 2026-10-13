from __future__ import annotations

import pytest

from analisis_acciones.app.error_handler import user_message_for
from analisis_acciones.models.errors import (
    AppError,
    DataError,
    ErrorCategory,
    InternalError,
    NetworkError,
    ProviderError,
    UserError,
)


@pytest.mark.parametrize(
    ("cls", "category"),
    [
        (UserError, ErrorCategory.USER),
        (NetworkError, ErrorCategory.NETWORK),
        (DataError, ErrorCategory.DATA),
        (ProviderError, ErrorCategory.PROVIDER),
        (InternalError, ErrorCategory.INTERNAL),
    ],
)
def test_categories_and_default_messages(cls: type[AppError], category: ErrorCategory) -> None:
    err = cls("technical detail")
    assert err.category is category
    assert err.user_message  # never empty
    assert str(err) == "technical detail"


def test_custom_user_message() -> None:
    err = UserError("ticker 'XYZ!' invalid", user_message="Ticker no válido.")
    assert err.user_message == "Ticker no válido."


def test_unknown_exception_gets_generic_message() -> None:
    assert user_message_for(KeyError("x")) == InternalError.default_user_message
    assert user_message_for(NetworkError("timeout")) == NetworkError.default_user_message
