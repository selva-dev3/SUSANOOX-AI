from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import suppress
from pathlib import Path

import pytest
from textual.widgets import Input, Static, TextArea
from textual.worker import WorkerCancelled

from susanoox.config.credentials import Credential, CredentialSource
from susanoox.config.settings import Settings
from susanoox.models.protocol import ConversationMessage
from susanoox.ui.app import SusanooxApp
from susanoox.ui.screens.conversation import ConversationScreen
from susanoox.ui.screens.onboarding import OnboardingScreen
from susanoox.ui.widgets.messages import MessageBubble
from susanoox.utils.errors import AuthenticationError
from tests.conftest import FakeChatClient


class MemoryCredentialStore:
    def __init__(self, credential: Credential | None = None) -> None:
        self.credential = credential
        self.delete_count = 0

    def get_credential(self) -> Credential | None:
        return self.credential

    def set_api_key(self, api_key: str) -> None:
        self.credential = Credential(api_key, CredentialSource.KEYRING)

    def delete_api_key(self) -> None:
        self.delete_count += 1
        self.credential = None


class BlockingValidationClient(FakeChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def validate_api_key(self) -> None:
        self.started.set()
        await self.release.wait()


class RejectingValidationClient(FakeChatClient):
    async def validate_api_key(self) -> None:
        raise AuthenticationError("The supplied API key is invalid.")


class ClosableStreamClient(FakeChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.stream_closed = False

    async def stream_chat(
        self, messages: Sequence[ConversationMessage]
    ) -> AsyncGenerator[str, None]:
        self.requests.append(tuple(messages))
        try:
            yield "a"
            await asyncio.Event().wait()
        finally:
            self.stream_closed = True


class AuthenticationAfterFlushClient(FakeChatClient):
    def __init__(self, render_failed: asyncio.Event) -> None:
        super().__init__()
        self._render_failed = render_failed

    async def stream_chat(
        self, messages: Sequence[ConversationMessage]
    ) -> AsyncGenerator[str, None]:
        self.requests.append(tuple(messages))
        yield "a"
        yield "b"
        await self._render_failed.wait()
        raise AuthenticationError("Authentication expired.")


def compose_plain_message(_message: MessageBubble) -> Sequence[Static]:
    """Avoid Textual's threaded Markdown parser in cancellation lifecycle tests."""
    return (Static("message"),)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(project_path=tmp_path)


async def test_missing_key_opens_masked_onboarding(tmp_path: Path) -> None:
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, OnboardingScreen)
        assert app.screen.query_one("#api-key-input", Input).password is True


async def test_stored_key_is_validated_before_conversation(tmp_path: Path) -> None:
    client = FakeChatClient()
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert client.validated
        assert isinstance(app.screen, ConversationScreen)


async def test_stored_key_is_never_placed_in_the_input(tmp_path: Path) -> None:
    client = BlockingValidationClient()
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await client.started.wait()
        screen = app.screen
        assert isinstance(screen, OnboardingScreen)
        input_widget = screen.query_one("#api-key-input", Input)
        assert input_widget.value == ""
        client.release.set()
        await pilot.pause()


async def test_environment_auth_failure_does_not_delete_keyring_key(tmp_path: Path) -> None:
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        app.require_authentication("Rejected", CredentialSource.ENVIRONMENT)
        await pilot.pause()
        assert store.delete_count == 0


async def test_environment_auth_failure_explains_override_and_allows_manual_key(
    tmp_path: Path,
) -> None:
    rejected = RejectingValidationClient()
    accepted = FakeChatClient()
    clients = iter((rejected, accepted))
    store = MemoryCredentialStore(Credential("environment-key", CredentialSource.ENVIRONMENT))
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: next(clients),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, OnboardingScreen)
        status = str(screen.query_one("#verification-status", Static).render())
        assert "SUSANOOX_API_KEY" in status
        assert "remove" in status

        key_input = screen.query_one("#api-key-input", Input)
        key_input.value = "replacement-key"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert accepted.validated
        assert store.credential == Credential("replacement-key", CredentialSource.KEYRING)
        assert isinstance(app.screen, ConversationScreen)


async def test_cancelled_authentication_closes_client(tmp_path: Path) -> None:
    client = BlockingValidationClient()
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await client.started.wait()
        screen = app.screen
        assert isinstance(screen, OnboardingScreen)
        screen.workers.cancel_group(  # pyright: ignore[reportUnknownMemberType]
            screen, "authentication"
        )
        await pilot.pause()
        assert client.closed


async def test_cancelling_during_render_closes_the_model_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ClosableStreamClient()
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    render_started = asyncio.Event()
    rendered: list[str] = []

    async def block_first_render(_message: MessageBubble, content: str) -> None:
        rendered.append(content)
        if len(rendered) == 1:
            render_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", block_first_render)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.stream_response("Prompt")
        await asyncio.wait_for(render_started.wait(), timeout=1)
        worker.cancel()
        with suppress(WorkerCancelled):
            await worker.wait()
        assert client.stream_closed
        assert "excluded from context" in rendered[-1]
        app.exit()
        await pilot.pause()


async def test_cancel_during_final_render_preserves_committed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient(response=("a", "b"))
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))
    final_render_started = asyncio.Event()
    rendered: list[str] = []

    async def block_final_render(_message: MessageBubble, content: str) -> None:
        rendered.append(content)
        if content == "ab" and rendered.count("ab") == 1:
            final_render_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", block_final_render)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.stream_response("Prompt")
        await asyncio.wait_for(final_render_started.wait(), timeout=1)
        worker.cancel()
        with suppress(WorkerCancelled):
            await worker.wait()
        assert rendered[-1] == "ab"
        assert all("excluded from context" not in content for content in rendered)
        app.exit()
        await pilot.pause()


async def test_render_cleanup_failure_does_not_mask_authentication_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    render_failed = asyncio.Event()
    client = AuthenticationAfterFlushClient(render_failed)
    store = MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING))

    async def fail_delayed_render(_message: MessageBubble, content: str) -> None:
        if content == "ab":
            render_failed.set()
            raise ValueError("render failed")

    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", fail_delayed_render)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=store,
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.stream_response("Prompt")
        await worker.wait()
        await pilot.pause()

        assert isinstance(app.screen, OnboardingScreen)
        status = str(app.screen.query_one("#verification-status", Static).render())
        assert "Authentication expired" in status


@pytest.mark.parametrize("terminal_size", [(150, 30), (80, 24)])
async def test_prompt_remains_visible_in_short_terminals(
    tmp_path: Path, terminal_size: tuple[int, int]
) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=terminal_size) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        prompt = screen.query_one("#prompt-composer")

        assert prompt.display
        assert prompt.region.y >= 0
        assert prompt.region.bottom <= screen.size.height
        assert screen.has_class("-short")
        assert screen.query_one("#shortcut-bar").display is False
        assert screen.has_class("-compact") is (terminal_size[0] <= 80)


async def test_live_resize_updates_responsive_layout(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        compact_columns = list(screen.query(".welcome-column"))
        assert screen.has_class("-compact")
        assert screen.has_class("-short")
        assert screen.query_one("#shortcut-bar").display is False
        assert compact_columns[1].region.y > compact_columns[0].region.y

        await pilot.resize_terminal(120, 40)
        await pilot.pause()

        wide_columns = list(screen.query(".welcome-column"))
        assert screen.has_class("-compact") is False
        assert screen.has_class("-short") is False
        assert screen.query_one("#shortcut-bar").display
        assert wide_columns[1].region.y == wide_columns[0].region.y
        assert screen.query_one("#prompt-composer").region.bottom <= screen.size.height

        await pilot.resize_terminal(80, 24)
        await pilot.pause()

        compact_columns = list(screen.query(".welcome-column"))
        assert screen.has_class("-compact")
        assert screen.has_class("-short")
        assert screen.query_one("#shortcut-bar").display is False
        assert compact_columns[1].region.y > compact_columns[0].region.y
        assert screen.query_one("#prompt-composer").region.bottom <= screen.size.height


async def test_starter_action_populates_and_focuses_prompt(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        await pilot.click("#starter-explain")
        await pilot.pause()

        prompt_input = screen.query_one("#prompt-input", TextArea)
        assert prompt_input.text == "Explain a code concept"
        assert app.focused is prompt_input


async def test_clear_restores_welcome_without_removing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient(response=("Done",))
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        worker = screen.stream_response("Prompt")
        await worker.wait()
        await pilot.pause()
        assert screen.query_one("#welcome-panel").display is False
        view = screen.query_one("#conversation-view")
        for index in range(20):
            await view.mount(Static(f"Transcript line {index}", classes="message"))
        await pilot.pause()
        view.scroll_end(animate=False, force=True, immediate=True)
        await pilot.pause()
        assert view.scroll_y > 0

        screen.action_clear()
        await pilot.pause()
        await pilot.pause()

        assert screen.query_one("#welcome-panel").display is True
        assert len(screen.query(MessageBubble)) == 0
        assert len(view.query(".message")) == 0
        assert view.scroll_y == 0
        first_action = screen.query_one("#starter-explain")
        assert first_action.region.y >= view.region.y
        assert first_action.region.y < view.region.bottom
