from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from susanoox.utils.errors import CredentialError

SERVICE_NAME: Final = "susanoox"
ACCOUNT_NAME: Final = "api-key"
ENVIRONMENT_VARIABLE: Final = "SUSANOOX_API_KEY"


class CredentialSource(StrEnum):
    ENVIRONMENT = "environment"
    KEYRING = "keyring"


@dataclass(frozen=True, slots=True)
class Credential:
    value: str
    source: CredentialSource


class CredentialStore(Protocol):
    def get_credential(self) -> Credential | None: ...

    def set_api_key(self, api_key: str) -> None: ...

    def delete_api_key(self) -> None: ...


class SecureCredentialStore:
    """Use an environment override or the operating system credential backend."""

    def get_credential(self) -> Credential | None:
        environment_key = os.environ.get(ENVIRONMENT_VARIABLE, "").strip()
        if environment_key:
            return Credential(environment_key, CredentialSource.ENVIRONMENT)
        try:
            stored = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        except (KeyringError, RuntimeError) as error:
            raise CredentialError(_backend_error_message()) from error
        normalized = stored.strip() if stored else ""
        return Credential(normalized, CredentialSource.KEYRING) if normalized else None

    def set_api_key(self, api_key: str) -> None:
        normalized = api_key.strip()
        if not normalized:
            raise CredentialError("The API key cannot be empty.")
        try:
            keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, normalized)
        except (KeyringError, RuntimeError) as error:
            raise CredentialError(_backend_error_message()) from error

    def delete_api_key(self) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        except PasswordDeleteError:
            return
        except (KeyringError, RuntimeError) as error:
            raise CredentialError(_backend_error_message()) from error


def _backend_error_message() -> str:
    return (
        "Secure credential storage is unavailable. Configure an operating-system keyring "
        f"or set {ENVIRONMENT_VARIABLE} for the current process. Susanoox will not save the "
        "key as plaintext."
    )


__all__ = [
    "ENVIRONMENT_VARIABLE",
    "Credential",
    "CredentialSource",
    "CredentialStore",
    "NoKeyringError",
    "SecureCredentialStore",
]
