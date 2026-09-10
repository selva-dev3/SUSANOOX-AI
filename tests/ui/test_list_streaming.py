from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

import pytest
from rich.console import Console
from rich.markdown import Markdown
from textual.widgets import Static
from textual.worker import WorkerCancelled

from susanoox.config.credentials import Credential, CredentialSource
from susanoox.config.settings import ModelName, Settings
from susanoox.models.protocol import ConversationMessage, StreamEvent, TextDelta
from susanoox.ui.app import SusanooxApp
from susanoox.ui.screens.conversation import ConversationScreen
from susanoox.ui.widgets.messages import MessageBubble
from susanoox.ui.widgets.prompt import PromptInput
from tests.conftest import FakeChatClient
from tests.ui.test_app import MemoryCredentialStore


class ListClient(FakeChatClient):
    async def stream_chat(
        self, messages: Sequence[ConversationMessage], *, model: ModelName
    ) -> AsyncGenerator[StreamEvent, None]:
        for chunk in self.response:
            await asyncio.sleep(0.012)
            yield TextDelta(chunk)


@pytest.mark.parametrize("kind", ["numbered", "bullets", "nested"])
async def test_slow_list_stream_keeps_app_usable(tmp_path: Path, kind: str) -> None:
    content = "\n".join(
        f"{index}. Item **bold**"
        if kind == "numbered"
        else f"- Item {index}"
        if kind == "bullets"
        else f"{index}. Item\n   - child"
        for index in range(1, 16)
    )
    client = ListClient(response=tuple(content[i : i + 9] for i in range(0, len(content), 9)))
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path, auto_context=False),
        credential_store=MemoryCredentialStore(Credential("test-only", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        screen.query_one(PromptInput).text = "List items"
        screen.action_submit()
        worker = next(worker for worker in screen.workers if worker.group == "chat")
        await asyncio.wait_for(worker.wait(), 30)
        assert app.is_running
        assert list(screen.query(MessageBubble))[-1].markdown_text == content
        client.response = ("Still here",)
        screen.query_one(PromptInput).text = "Hello again"
        screen.action_submit()
        worker = next(worker for worker in screen.workers if worker.group == "chat")
        await asyncio.wait_for(worker.wait(), 10)
        assert list(screen.query(MessageBubble))[-1].markdown_text == "Still here"


async def test_markdown_updates_reuse_the_content_widget(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path, auto_context=False),
        credential_store=MemoryCredentialStore(Credential("test-only", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        worker = screen.stream_response("Show code")
        await worker.wait()
        bubble = list(screen.query(MessageBubble))[-1]
        widget = bubble.query_one(".message-content", Static)
        content = "1. First\n2. Second\n\n```python\ndef hello():\n    return 42\n```"
        await bubble.update_content(content)
        assert bubble.query_one(".message-content", Static) is widget
        renderable = widget.content
        assert isinstance(renderable, Markdown)
        console = Console(width=80, force_terminal=True, no_color=False, color_system="truecolor")
        with console.capture() as capture:
            console.print(renderable)
        output = capture.get()
        assert "First" in output and "Second" in output
        assert "hello" in output and "42" in output
        assert "\x1b[" in output  # Syntax/style spans survive the renderable update.


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancel_real_markdown_list(tmp_path: Path, shutdown: bool) -> None:
    client = ListClient(response=tuple(f"{i}. Item\n" for i in range(1, 100)))
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path, auto_context=False),
        credential_store=MemoryCredentialStore(Credential("test-only", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        screen.query_one(PromptInput).text = "List items"
        screen.action_submit()
        worker = next(worker for worker in screen.workers if worker.group == "chat")
        await asyncio.sleep(0.2)
        if shutdown:
            app.exit()
        else:
            await pilot.press("escape")
            with pytest.raises(WorkerCancelled):
                await worker.wait()
            assert app.is_running
            assert not screen.query_one(PromptInput).disabled
