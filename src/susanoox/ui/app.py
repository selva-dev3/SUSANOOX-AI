from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import App

from susanoox.config.credentials import CredentialSource, CredentialStore
from susanoox.config.settings import Settings
from susanoox.models.client import SusanooxClient
from susanoox.models.protocol import ChatClient
from susanoox.sessions.storage import SessionStore
from susanoox.ui.clipboard import copy_to_system_clipboard
from susanoox.ui.screens.conversation import ConversationScreen, PendingRequest
from susanoox.ui.screens.onboarding import OnboardingScreen
from susanoox.utils.errors import CredentialError

ClientFactory = Callable[[str, Settings], ChatClient]


def _default_client_factory(api_key: str, settings: Settings) -> ChatClient:
    return SusanooxClient(api_key=api_key, settings=settings)


class SusanooxApp(App[None]):
    CSS_PATH = "susanoox.tcss"
    TITLE = "Susanoox"
    ENABLE_COMMAND_PALETTE = False
    # Textual's responsive breakpoint API requires mutable lists.
    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = [  # noqa: RUF012
        (0, "-compact"),
        (81, "-wide"),
    ]
    VERTICAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] | None = [  # noqa: RUF012
        (0, "-short"),
        (36, "-tall"),
    ]

    def __init__(
        self,
        *,
        settings: Settings,
        credential_store: CredentialStore,
        client_factory: ClientFactory = _default_client_factory,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.credential_store = credential_store
        self._client_factory = client_factory
        self._pending_request: PendingRequest | None = None
        self._session_store = session_store
        self._session_id = session_id

    def on_mount(self) -> None:
        startup_error: str | None = None
        try:
            credential = self.credential_store.get_credential()
        except CredentialError as error:
            credential = None
            startup_error = str(error)
        screen = OnboardingScreen(
            existing_credential=credential,
            startup_error=startup_error,
        )
        self.push_screen(screen)

    def create_client(self, api_key: str) -> ChatClient:
        return self._client_factory(api_key, self.settings)

    def copy_to_clipboard(self, text: str) -> None:
        super().copy_to_clipboard(text)
        self.run_worker(
            lambda: copy_to_system_clipboard(text),
            group="clipboard",
            exclusive=True,
            thread=True,
            exit_on_error=False,
        )

    def enter_conversation(self, client: ChatClient, credential_source: CredentialSource) -> None:
        pending_request = self._pending_request
        self._pending_request = None
        screen = ConversationScreen(
            settings=self.settings,
            client=client,
            credential_source=credential_source,
            pending_request=pending_request,
            session_store=self._session_store,
            session_id=self._session_id,
        )
        self.switch_screen(screen)  # pyright: ignore[reportUnknownMemberType]

    def require_authentication(
        self,
        message: str,
        source: CredentialSource,
        *,
        pending_request: PendingRequest | None = None,
    ) -> None:
        self._pending_request = pending_request
        if source is CredentialSource.KEYRING:
            try:
                self.credential_store.delete_api_key()
            except CredentialError as error:
                message = f"{message}\n\n{error}"
        elif source is CredentialSource.ENVIRONMENT:
            message = (
                f"{message}\n\nThe rejected key came from SUSANOOX_API_KEY. "
                "Update or remove that environment variable before restarting."
            )
        screen = OnboardingScreen(startup_error=message)
        self.switch_screen(screen)  # pyright: ignore[reportUnknownMemberType]
