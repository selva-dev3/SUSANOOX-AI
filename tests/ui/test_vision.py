from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

import pytest
from textual import events
from textual.widgets import Input, Static

from susanoox.config.credentials import Credential, CredentialSource
from susanoox.config.settings import ModelName
from susanoox.models.protocol import ConversationMessage, ImageAttachment, StreamEvent
from susanoox.ui.app import SusanooxApp
from susanoox.ui.screens.conversation import ConversationScreen
from susanoox.ui.screens.onboarding import OnboardingScreen
from susanoox.ui.widgets.messages import MessageBubble
from susanoox.ui.widgets.prompt import PromptComposer, PromptInput
from susanoox.utils.errors import AuthenticationError, ServiceResponseError
from tests.conftest import FakeChatClient
from tests.ui.test_app import MemoryCredentialStore, make_settings


class FailOnceClient(FakeChatClient):
    async def stream_chat(
        self, messages: Sequence[ConversationMessage], *, model: ModelName
    ) -> AsyncGenerator[StreamEvent, None]:
        if not self.requests:
            self.requests.append(tuple(messages))
            self.models.append(model)
            raise ServiceResponseError("Temporary service failure")
        async for event in super().stream_chat(messages, model=model):
            yield event


class AuthenticationFailureClient(FakeChatClient):
    async def stream_chat(
        self, messages: Sequence[ConversationMessage], *, model: ModelName
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        raise AuthenticationError("Authentication expired")
        yield  # pragma: no cover - keeps this method an async generator


class AuthenticationAfterSuccessClient(FakeChatClient):
    async def stream_chat(
        self, messages: Sequence[ConversationMessage], *, model: ModelName
    ) -> AsyncGenerator[StreamEvent, None]:
        if self.requests:
            self.requests.append(tuple(messages))
            self.models.append(model)
            raise AuthenticationError("Authentication expired")
        async for event in super().stream_chat(messages, model=model):
            yield event


@pytest.mark.parametrize("fail_first", [False, True])
@pytest.mark.parametrize("prompt", ["Read this", ""])
async def test_direct_clipboard_vision_and_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_first: bool, prompt: str
) -> None:
    client = FailOnceClient() if fail_first else FakeChatClient()
    image = ImageAttachment("clipboard.png", "image/png", b"synthetic")
    monkeypatch.setattr("susanoox.ui.screens.conversation.read_clipboard_image", lambda: image)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        composer = screen.query_one(PromptComposer)
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert composer.attachment == image
        assert client.requests == []
        assert "susanoox-vision" in str(screen.query_one("#connection-status", Static).render())
        app.post_message(events.Paste(prompt))
        await pilot.pause()
        assert composer.text == prompt
        await pilot.press("enter")
        await pilot.pause()
        if fail_first:
            assert composer.text == prompt
            assert composer.attachment == image
            assert len(client.requests) == 1
            await pilot.press("enter")
            await pilot.pause()
            assert len(client.requests[-1]) == 2  # No failed exchange in history.
            assert (
                len([bubble for bubble in screen.query(MessageBubble) if bubble.kind == "user"])
                == 1
            )
        assert client.models[-1] == "susanoox-vision"
        assert client.requests[-1][-1].images == (image,)
        assert composer.attachment is None
        composer.query_one(PromptInput).load_text("/model susanoox-fast")
        await pilot.press("enter")
        await pilot.pause()
        assert "susanoox-vision" in str(screen.query_one("#connection-status", Static).render())
        composer.query_one(PromptInput).load_text("Explain more")
        await pilot.press("enter")
        await pilot.pause()
        assert client.models[-1] == "susanoox-vision"
        assert any(message.images == (image,) for message in client.requests[-1])
        screen.action_clear()
        composer.query_one(PromptInput).load_text("/model susanoox-fast")
        await pilot.press("enter")
        await pilot.pause()
        assert "susanoox-fast" in str(screen.query_one("#connection-status", Static).render())


async def test_authentication_restores_vision_draft_after_new_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = AuthenticationFailureClient()
    accepted = FakeChatClient()
    clients = iter((rejected, accepted))
    image = ImageAttachment("clipboard.png", "image/png", b"synthetic")
    monkeypatch.setattr("susanoox.ui.screens.conversation.read_clipboard_image", lambda: image)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: next(clients),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        app.post_message(events.Paste("Read after login"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, OnboardingScreen)
        key_input = app.screen.query_one("#api-key-input", Input)
        key_input.value = "replacement-key"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        composer = screen.query_one(PromptComposer)
        assert composer.text == "Read after login"
        assert composer.attachment == image
        assert "susanoox-vision" in str(screen.query_one("#connection-status", Static).render())
        assert accepted.requests == []


async def test_followup_authentication_preserves_image_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired = AuthenticationAfterSuccessClient()
    accepted = FakeChatClient()
    clients = iter((expired, accepted))
    image = ImageAttachment("clipboard.png", "image/png", b"synthetic")
    monkeypatch.setattr("susanoox.ui.screens.conversation.read_clipboard_image", lambda: image)
    app = SusanooxApp(
        settings=make_settings(tmp_path),
        credential_store=MemoryCredentialStore(Credential("stored-key", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: next(clients),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        app.post_message(events.Paste("Describe it"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        app.post_message(events.Paste("Explain the lower panel"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, OnboardingScreen)
        app.screen.query_one("#api-key-input", Input).value = "replacement-key"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        composer = screen.query_one(PromptComposer)
        assert composer.text == "Explain the lower panel"
        assert composer.attachment is None
        assert accepted.requests == []
        visible = [bubble for bubble in screen.query(MessageBubble) if bubble.kind != "error"]
        assert [bubble.kind for bubble in visible] == ["user", "assistant"]
        await pilot.press("enter")
        await pilot.pause()
        request = accepted.requests[-1]
        assert [message.role for message in request] == ["system", "user", "assistant", "user"]
        assert request[1].images == (image,)
        assert request[-1].content == "Explain the lower panel"
