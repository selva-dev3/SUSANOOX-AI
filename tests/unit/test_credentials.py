from __future__ import annotations

import pytest
from keyring.errors import NoKeyringError

from susanoox.config.credentials import Credential, CredentialSource, SecureCredentialStore
from susanoox.utils.errors import CredentialError


def test_environment_key_has_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUSANOOX_API_KEY", " environment-key ")

    def get_password(_service: str, _account: str) -> str:
        return "stored-key"

    monkeypatch.setattr("keyring.get_password", get_password)

    assert SecureCredentialStore().get_credential() == Credential(
        "environment-key", CredentialSource.ENVIRONMENT
    )


def test_key_is_stored_in_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str, str]] = []
    monkeypatch.delenv("SUSANOOX_API_KEY", raising=False)

    def set_password(service: str, account: str, key: str) -> None:
        captured.append((service, account, key))

    monkeypatch.setattr("keyring.set_password", set_password)

    SecureCredentialStore().set_api_key(" secret-key ")

    assert captured == [("susanoox", "api-key", "secret-key")]


def test_unavailable_keyring_never_falls_back_to_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUSANOOX_API_KEY", raising=False)

    def unavailable(*_args: object) -> None:
        raise NoKeyringError("no backend")

    monkeypatch.setattr("keyring.get_password", unavailable)

    with pytest.raises(CredentialError, match="will not save"):
        SecureCredentialStore().get_credential()


def test_whitespace_only_keyring_value_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUSANOOX_API_KEY", raising=False)

    def whitespace_key(_service: str, _account: str) -> str:
        return "   "

    monkeypatch.setattr("keyring.get_password", whitespace_key)

    assert SecureCredentialStore().get_credential() is None
