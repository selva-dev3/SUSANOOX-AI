from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, cast

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, LoadingIndicator, Static

from susanoox.config.credentials import (
    ENVIRONMENT_VARIABLE,
    Credential,
    CredentialSource,
)
from susanoox.models.protocol import ChatClient
from susanoox.utils.errors import AuthenticationError, SusanooxError

if TYPE_CHECKING:
    from susanoox.ui.app import SusanooxApp

_LOGGER = logging.getLogger(__name__)


class OnboardingScreen(Screen[None]):
    BINDINGS: ClassVar = [
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        existing_credential: Credential | None = None,
        startup_error: str | None = None,
    ) -> None:
        super().__init__()
        self._existing_credential = existing_credential
        self._startup_error = startup_error

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="onboarding-card"):
                yield Static("SUSANOOX", id="onboarding-brand")
                yield Static("Secure terminal intelligence", id="onboarding-tagline")
                yield Label("An API key is required to continue.", id="key-instructions")
                yield Input(
                    placeholder="Enter your Susanoox API key",
                    password=True,
                    id="api-key-input",
                )
                yield Button("Verify & connect", variant="primary", id="verify-button")
                yield LoadingIndicator(id="verify-spinner")
                yield Static(self._startup_error or "", id="verification-status")
                yield Static(
                    "Uses your environment or operating system credential manager · Esc to exit",
                    id="credential-note",
                )

    def on_mount(self) -> None:
        self.query_one("#verify-spinner").display = False
        self.query_one(Input).focus()
        if self._existing_credential:
            credential = self._existing_credential
            self._existing_credential = None
            self.verify_key(
                credential.value,
                persist=False,
                source=credential.source,
            )

    @on(Button.Pressed, "#verify-button")
    @on(Input.Submitted, "#api-key-input")
    def submit_key(self) -> None:
        api_key = self.query_one(Input).value.strip()
        if not api_key:
            self._show_error("Enter a valid Susanoox API key.")
            return
        self.verify_key(api_key, persist=True, source=CredentialSource.KEYRING)

    @work(exclusive=True, group="authentication")
    async def verify_key(
        self,
        api_key: str,
        *,
        persist: bool,
        source: CredentialSource,
    ) -> None:
        self._set_busy(True)
        client: ChatClient | None = None
        ownership_transferred = False
        try:
            app = cast(
                "SusanooxApp",
                self.app,  # pyright: ignore[reportUnknownMemberType]
            )
            client = app.create_client(api_key)
            await client.validate_api_key()
            if persist:
                app.credential_store.set_api_key(api_key)
        except AuthenticationError as error:
            message = str(error)
            if source is CredentialSource.ENVIRONMENT:
                message = (
                    f"{message} The rejected key came from {ENVIRONMENT_VARIABLE}; "
                    "update or remove that environment variable before your next launch."
                )
            self._show_error(message)
            self._set_busy(False)
            return
        except SusanooxError as error:
            self._show_error(str(error))
            self._set_busy(False)
            return
        except Exception:
            _LOGGER.error("Unexpected API-key verification failure")
            self._show_error("API key verification failed unexpectedly. Please try again.")
            self._set_busy(False)
            return
        else:
            self.query_one("#verification-status", Static).update(
                "✓ API key verified   ✓ Connected   ✓ Ready"
            )
            app.enter_conversation(client, source)
            ownership_transferred = True
        finally:
            if client is not None and not ownership_transferred:
                try:
                    await client.close()
                except Exception:
                    _LOGGER.warning("Unable to close a rejected authentication client")

    def action_quit(self) -> None:
        app = cast(
            "SusanooxApp",
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )
        app.exit()

    def _set_busy(self, busy: bool) -> None:
        self.query_one(Input).disabled = busy
        self.query_one(Button).disabled = busy
        self.query_one("#verify-spinner").display = busy
        if busy:
            self.query_one("#verification-status", Static).update("Verifying API key…")

    def _show_error(self, message: str) -> None:
        status = self.query_one("#verification-status", Static)
        status.update(f"✗ {message}")
        status.add_class("error")
