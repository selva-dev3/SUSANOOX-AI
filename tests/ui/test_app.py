from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Sequence
from contextlib import suppress
from pathlib import Path

import pytest
from textual import events
from textual.widgets import Button, Input, Static, TextArea
from textual.worker import WorkerCancelled

from susanoox.config.credentials import Credential, CredentialSource
from susanoox.config.settings import ModelName, Settings
from susanoox.models.protocol import ConversationMessage, ImageAttachment, StreamEvent, TextDelta
from susanoox.ui.app import SusanooxApp
from susanoox.ui.screens.conversation import ConversationScreen
from susanoox.ui.screens.model_picker import ModelPickerScreen
from susanoox.ui.screens.onboarding import OnboardingScreen
from susanoox.ui.widgets.messages import ConversationView, MessageBubble, MessageKind
from susanoox.ui.widgets.prompt import PromptComposer, PromptInput
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
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        try:
            yield TextDelta("a")
            await asyncio.Event().wait()
        finally:
            self.stream_closed = True


class AuthenticationAfterFlushClient(FakeChatClient):
    def __init__(self, render_failed: asyncio.Event) -> None:
        super().__init__()
        self._render_failed = render_failed

    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        yield TextDelta("a")
        yield TextDelta("b")
        await self._render_failed.wait()
        raise AuthenticationError("Authentication expired.")


def compose_plain_message(_message: MessageBubble) -> Sequence[Static]:
    """Avoid Textual's threaded Markdown parser in cancellation lifecycle tests."""
    return (Static("message"),)


async def update_plain_message(message: MessageBubble, content: str) -> None:
    message.query_one(Static).update(content)


@pytest.mark.parametrize("after_start", [False, True])
async def test_clear_invalidates_pending_local_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_start: bool
) -> None:
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    started = asyncio.Event()
    release = asyncio.Event()
    original = ConversationView.add_message

    async def delayed_mount(
        view: ConversationView, content: str, *, kind: MessageKind
    ) -> MessageBubble:
        started.set()
        await release.wait()
        return await original(view, content, kind=kind)

    monkeypatch.setattr(ConversationView, "add_message", delayed_mount)
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.show_local_message("help output")
        if after_start:
            await asyncio.wait_for(started.wait(), 2)
        screen.action_clear()
        release.set()
        await worker.wait()
        await pilot.pause()
        assert screen.query_one("#welcome-panel").display
        assert not list(screen.query(MessageBubble))


async def test_public_prompt_events_preserve_typing_and_paste(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        await pilot.press("a", "b")
        app.post_message(events.Paste("Explain this image.png"))
        await pilot.pause()
        assert prompt.text == "abExplain this image.png"


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


async def test_conversation_uses_compact_terminal_launch_layout(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        welcome = screen.query_one("#welcome-panel")
        assert "SUSANOOX" in str(screen.query_one("#welcome-title", Static).render())
        assert "██" in str(screen.query_one("#welcome-mark", Static).render())
        assert "No recent activity" in str(screen.query_one("#recent-activity", Static).render())
        assert welcome.region.width <= 136

        prompt = screen.query_one("#prompt-composer")
        assert prompt.region.height == 3
        assert screen.query_one("#send-button", Button).display is True


async def test_compact_send_button_submits_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    submitted_prompts: list[str] = []

    def record_submission(screen: ConversationScreen) -> None:
        submitted_prompts.append(screen.query_one("#prompt-input", TextArea).text)

    monkeypatch.setattr(ConversationScreen, "action_submit", record_submission)
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
        screen.query_one("#prompt-input", TextArea).text = "Explain this module"

        composer = screen.query_one("#prompt-composer")
        send_button = screen.query_one("#send-button", Button)
        assert send_button.region.y >= composer.content_region.y
        assert send_button.region.bottom <= composer.content_region.bottom
        assert "Send" in app.export_screenshot()

        await pilot.click("#send-button")
        await pilot.pause()

        assert submitted_prompts == ["Explain this module"]


async def test_enter_submits_and_shift_enter_inserts_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    submitted_prompts: list[str] = []

    def record_submission(screen: ConversationScreen) -> None:
        submitted_prompts.append(screen.query_one("#prompt-input", TextArea).text)

    monkeypatch.setattr(ConversationScreen, "action_submit", record_submission)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        prompt = app.screen.query_one("#prompt-input", TextArea)
        prompt.text = "First line"
        prompt.move_cursor((0, len(prompt.text)))

        await pilot.press("shift+enter")
        assert prompt.text == "First line\n"

        await pilot.press("enter")
        assert submitted_prompts == ["First line\n"]


async def test_model_command_shows_all_models_and_switches_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", update_plain_message)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        conversation = app.screen
        assert isinstance(conversation, ConversationScreen)
        conversation.query_one("#prompt-input", TextArea).text = "/model"

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ModelPickerScreen)
        assert len(app.screen.query(".model-option")) == 4
        assert app.screen.query_one("#model-susanoox-embed", Button).disabled
        for option in app.screen.query(".model-option"):
            assert option.region.y >= 0
            assert option.region.bottom <= app.screen.size.height

        await pilot.click("#model-susanoox-large")
        await pilot.pause()

        assert app.screen is conversation
        status = str(conversation.query_one("#connection-status", Static).render())
        assert "susanoox-large" in status

        worker = conversation.stream_response("Use the selected model")
        await worker.wait()
        assert client.models[-1] == "susanoox-large"


async def test_usage_command_is_local_and_reports_exact_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", update_plain_message)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.stream_response("Count this request")
        await worker.wait()
        request_count = len(client.requests)
        screen.query_one("#prompt-input", TextArea).text = "/usage"

        await pilot.press("enter")
        await pilot.pause()

        assert len(client.requests) == request_count
        usage_message = list(screen.query(MessageBubble))[-1]
        assert "Prompt: 3 tokens" in usage_message.markdown_text
        assert "Completion: 2 tokens" in usage_message.markdown_text
        assert "Total: 5 tokens" in usage_message.markdown_text

        client.usage = None
        await screen.stream_response("No usage metadata").wait()
        screen.query_one("#prompt-input", TextArea).text = "/usage"
        await pilot.press("enter")
        await pilot.pause()
        usage_message = list(screen.query(MessageBubble))[-1]
        assert "Partial session usage" in usage_message.markdown_text
        assert "1 request(s) have unknown usage" in usage_message.markdown_text


async def test_pending_and_replaced_attachment_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    slow_finished = threading.Event()
    slow = ImageAttachment("slow.png", "image/png", b"slow")
    fast = ImageAttachment("fast.png", "image/png", b"fast")

    def loader(path: Path) -> ImageAttachment:
        if path.name == "slow.png":
            started.set()
            release.wait(timeout=5)
            slow_finished.set()
            return slow
        return fast

    monkeypatch.setattr("susanoox.ui.screens.conversation.load_image_file", loader)
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ConversationScreen)
            screen.load_path_attachment(Path("slow.png"))
            assert await asyncio.to_thread(started.wait, 2)
            composer = screen.query_one(PromptComposer)
            screen.query_one("#prompt-input", TextArea).text = "Read it"
            screen.action_submit()
            assert client.requests == []
            assert composer.text == "Read it"

            screen.load_path_attachment(Path("fast.png"))
            for worker in list(screen.workers):
                if not worker.is_cancelled:
                    await worker.wait()
            assert composer.attachment == fast
            release.set()
            assert await asyncio.to_thread(slow_finished.wait, 2)
            await pilot.pause()
            assert composer.attachment == fast
    finally:
        release.set()


async def test_cancelled_attachment_does_not_reappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def loader() -> ImageAttachment:
        started.set()
        release.wait(timeout=5)
        finished.set()
        return ImageAttachment("clipboard.png", "image/png", b"image")

    monkeypatch.setattr("susanoox.ui.screens.conversation.read_clipboard_image", loader)
    client = FakeChatClient()
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ConversationScreen)
            screen.query_one("#prompt-input", TextArea).text = "/paste-image"
            await pilot.press("enter")
            assert await asyncio.to_thread(started.wait, 2)
            screen.action_cancel()
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            await pilot.pause()
            assert screen.query_one(PromptComposer).attachment is None
            assert client.requests == []
    finally:
        release.set()


async def test_embed_model_is_shown_but_rejected_for_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        screen.query_one("#prompt-input", TextArea).text = "/model susanoox-embed"

        await pilot.press("enter")
        await pilot.pause()

        assert client.requests == []
        error_message = list(screen.query(MessageBubble))[-1]
        assert "embeddings" in error_message.markdown_text
        assert "cannot be used for conversation" in error_message.markdown_text


async def test_image_attachment_can_be_sent_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeChatClient()
    monkeypatch.setattr(MessageBubble, "compose", compose_plain_message)
    monkeypatch.setattr(MessageBubble, "update_content", update_plain_message)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    attachment = ImageAttachment(
        filename="screen.png",
        media_type="image/png",
        data=b"image-bytes",
    )

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        composer = screen.query_one(PromptComposer)
        composer.set_attachment(attachment)
        await pilot.pause()
        attachment_button = screen.query_one("#attachment-button", Button)
        assert attachment_button.display
        assert "screen.png" in str(attachment_button.label)

        await pilot.click("#attachment-button")
        await pilot.pause()

        assert composer.attachment is None
        assert attachment_button.display is False

        composer.set_attachment(attachment)
        screen.query_one("#prompt-input", TextArea).text = "Read this image"
        screen.action_submit()
        worker = list(screen.workers)[-1]
        await worker.wait()

        assert client.requests[-1][-1].images == (attachment,)
        assert composer.attachment is None


async def test_long_project_name_does_not_push_starters_out_of_compact_view(
    tmp_path: Path,
) -> None:
    client = FakeChatClient()
    settings = Settings(project_path=tmp_path / ("long-project-name-" * 6))
    app = SusanooxApp(
        settings=settings,
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        context = screen.query_one("#welcome-context")
        view = screen.query_one("#conversation-view")
        assert context.region.height == 1
        for starter_id in ("starter-explain", "starter-plan", "starter-debug"):
            starter = screen.query_one(f"#{starter_id}")
            assert starter.region.y >= view.region.y
            assert starter.region.bottom <= view.region.bottom


async def test_project_context_displays_markup_like_name_literally(tmp_path: Path) -> None:
    client = FakeChatClient()
    project_name = "[bold]project"
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path / project_name),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)

        rendered_context = screen.query_one("#welcome-context", Static).render()
        assert project_name in str(rendered_context)


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
