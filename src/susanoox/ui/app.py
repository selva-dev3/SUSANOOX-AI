from __future__ import annotations

from collections.abc import Callable

from textual.app import App
from textual.events import Resize

from susanoox.config.credentials import CredentialSource, CredentialStore
from susanoox.config.settings import Settings
from susanoox.models.client import SusanooxClient
from susanoox.models.protocol import ChatClient
from susanoox.ui.screens.conversation import ConversationScreen
from susanoox.ui.screens.onboarding import OnboardingScreen
from susanoox.utils.errors import CredentialError

ClientFactory = Callable[[str, Settings], ChatClient]


def _default_client_factory(api_key: str, settings: Settings) -> ChatClient:
    return SusanooxClient(api_key=api_key, settings=settings)


class SusanooxApp(App[None]):
    CSS_PATH = "susanoox.tcss"
    TITLE = "Susanoox"
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        *,
        settings: Settings,
        credential_store: CredentialStore,
        client_factory: ClientFactory = _default_client_factory,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.credential_store = credential_store
        self._client_factory = client_factory

    def on_mount(self) -> None:
        self._update_responsive_class()
        startup_error: str | None = None
        try:
            credential = self.credential_store.get_credential()
        except CredentialError as error:
            credential = None
            startup_error = str(error)
        self.push_screen(
            OnboardingScreen(existing_credential=credential, startup_error=startup_error)
        )

    def create_client(self, api_key: str) -> ChatClient:
        return self._client_factory(api_key, self.settings)

    def enter_conversation(self, client: ChatClient, credential_source: CredentialSource) -> None:
        screen = ConversationScreen(
            settings=self.settings,
            client=client,
            credential_source=credential_source,
        )
        self.switch_screen(screen)  # pyright: ignore[reportUnknownMemberType]

    def require_authentication(self, message: str, source: CredentialSource) -> None:
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

    def on_resize(self, _event: Resize) -> None:
        self._update_responsive_class()

    def _update_responsive_class(self) -> None:
        self.set_class(self.size.width < 80, "-compact")
