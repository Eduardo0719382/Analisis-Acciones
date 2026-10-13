"""Application error taxonomy.

Every error carries a technical message (for logs) and a short user-facing
message in Spanish (for the UI). The category lets the UI choose how to
present it without inspecting exception types.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    USER = "user"
    NETWORK = "network"
    DATA = "data"
    PROVIDER = "provider"
    INTERNAL = "internal"


class AppError(Exception):
    category: ErrorCategory = ErrorCategory.INTERNAL
    default_user_message: str = (
        "Se produjo un error interno. Consulte el registro para más detalles."
    )

    def __init__(self, message: str, *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.user_message = user_message or self.default_user_message


class UserError(AppError):
    category = ErrorCategory.USER
    default_user_message = "La entrada no es válida."


class NetworkError(AppError):
    category = ErrorCategory.NETWORK
    default_user_message = "No se pudo conectar. Compruebe su conexión a Internet."


class DataError(AppError):
    category = ErrorCategory.DATA
    default_user_message = "Los datos recibidos están incompletos o no son válidos."


class ProviderError(AppError):
    category = ErrorCategory.PROVIDER
    default_user_message = "El proveedor de datos devolvió un error."


class InternalError(AppError):
    category = ErrorCategory.INTERNAL
