from __future__ import annotations

import asyncio
import logging
from contextlib import aclosing
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static, TextArea
from textual.worker import Worker

from susanoox import __version__
from susanoox.config.credentials import CredentialSource
from susanoox.config.settings import Settings
from susanoox.conversations.service import ConversationService
from susanoox.models.protocol import ChatClient
from susanoox.ui.streaming import StreamRenderer, cancelled_content
from susanoox.ui.widgets.activity import ActivityBar
from susanoox.ui.widgets.header import AppHeader
from susanoox.ui.widgets.messages import ConversationView
from susanoox.ui.widgets.prompt import PromptComposer
from susanoox.utils.errors import AuthenticationError, SusanooxError

if TYPE_CHECKING:
    from susanoox.ui.app import SusanooxApp

_STREAM_RENDER_INTERVAL_SECONDS = 0.05
_LOGGER = logging.getLogger(__name__)
_STARTER_PROMPTS = {
    "starter-explain": "Explain a code concept",
    "starter-plan": "Plan a focused change",
    "starter-debug": "Debug an error message",
}


class ConversationScreen(Screen[None]):
    BINDINGS: ClassVar = [
        Binding("ctrl+enter", "submit", "Send", priority=True),
        Binding("ctrl+k", "clear", "Clear"),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        settings: Settings,
        client: ChatClient,
        credential_source: CredentialSource,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._client = client
        self._conversation = ConversationService(client)
        self._credential_source = credential_source
        self._chat_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader(
            version=__version__,
            model=self._settings.model,
            project_path=self._settings.project_path,
        )
        with Container(id="conversation-shell"):
            with ConversationView(id="conversation-view"):
                with Vertical(id="welcome-panel"):
                    yield Static(f" SUSANOOX  v{__version__} ", id="welcome-title")
                    with Horizontal(id="welcome-columns"):
                        with Vertical(classes="welcome-column welcome-identity"):
                            yield Static("Welcome back.", id="welcome-greeting")
                            yield Static("  /\\\n /  \\\n/\\  /\\\n  \\/", id="welcome-mark")
                            yield Static(
                                Text(
                                    f"{self._settings.model}  ·  {self._settings.project_path.name}"
                                ),
                                id="welcome-context",
                            )
                        with Vertical(classes="welcome-column welcome-actions"):
                            yield Static(
                                "TIPS FOR GETTING STARTED", classes="welcome-section-title"
                            )
                            for starter_id, prompt in _STARTER_PROMPTS.items():
                                yield Button(
                                    prompt,
                                    id=starter_id,
                                    classes="starter-action",
                                )
                            yield Static(
                                "RECENT ACTIVITY",
                                classes="welcome-section-title recent-title",
                            )
                            yield Static("No recent activity", id="recent-activity")
                    yield Static(
                        "Ctrl+Enter to send  ·  Esc to cancel",
                        id="welcome-hint",
                    )
            yield ActivityBar(id="activity-bar")
            yield PromptComposer(id="prompt-composer")
            yield Static(
                "Ctrl+Enter send  ·  Esc cancel  ·  Ctrl+K clear  ·  Ctrl+Q quit",
                id="shortcut-bar",
            )

    def on_mount(self) -> None:
        self.query_one(PromptComposer).focus_input()

    @on(Button.Pressed, "#send-button")
    def send_button_pressed(self) -> None:
        self.action_submit()

    @on(Button.Pressed, ".starter-action")
    def starter_action_pressed(self, event: Button.Pressed) -> None:
        starter_id = event.button.id
        if starter_id is None:
            return
        prompt = _STARTER_PROMPTS.get(starter_id)
        if prompt is None:
            return
        prompt_input = self.query_one("#prompt-input", TextArea)
        prompt_input.text = prompt
        prompt_input.focus()

    def action_submit(self) -> None:
        composer = self.query_one(PromptComposer)
        prompt = composer.text.strip()
        if not prompt or (self._chat_worker is not None and self._chat_worker.is_running):
            return
        composer.clear()
        self._chat_worker = self.stream_response(prompt)

    @work(exclusive=True, group="chat")
    async def stream_response(self, prompt: str) -> None:
        view = self.query_one(ConversationView)
        self.query_one("#welcome-panel").display = False
        await view.add_message(prompt, kind="user")
        assistant_message = await view.add_message("", kind="assistant")
        self._set_busy(True, "Thinking…")
        renderer = StreamRenderer(interval_seconds=_STREAM_RENDER_INTERVAL_SECONDS)
        response_committed = False
        try:
            response_stream = self._conversation.send(prompt)
            async with aclosing(response_stream):
                async for delta in response_stream:
                    rendered = await renderer.add(delta, assistant_message.update_content)
                    if rendered:
                        view.scroll_end(animate=False)
            response_committed = True
            await renderer.finish(assistant_message.update_content)
            view.scroll_end(animate=False)
        except asyncio.CancelledError:
            await self._cleanup_renderer(renderer)
            if response_committed:
                await assistant_message.update_content(renderer.content)
                self._set_busy(False, "Ready")
                raise
            await assistant_message.update_content(cancelled_content(renderer.content))
            self._set_busy(False, "Cancelled")
            raise
        except AuthenticationError as error:
            await self._cleanup_renderer(renderer)
            app = cast(
                "SusanooxApp",
                self.app,  # pyright: ignore[reportUnknownMemberType]
            )
            app.require_authentication(str(error), self._credential_source)
            return
        except SusanooxError as error:
            await self._cleanup_renderer(renderer)
            assistant_message.remove()
            await view.add_message(str(error), kind="error")
            self._set_busy(False, "Request failed · retry available")
            return
        except Exception:
            await self._cleanup_renderer(renderer)
            assistant_message.remove()
            await view.add_message(
                "An unexpected response error occurred. Your API key was not exposed.", kind="error"
            )
            self._set_busy(False, "Request failed · retry available")
            return
        await self._cleanup_renderer(renderer)
        self._set_busy(False, "Ready")

    def action_cancel(self) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            self._chat_worker.cancel()

    def action_clear(self) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        self._conversation.clear()
        view = self.query_one(ConversationView)
        view.query(".message").remove()
        self.query_one("#welcome-panel").display = True
        view.call_after_refresh(
            view.scroll_home,
            animate=False,
            force=True,
            immediate=True,
        )
        self._set_busy(False, "Conversation cleared")

    def action_quit(self) -> None:
        app = cast(
            "SusanooxApp",
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )
        app.exit()

    async def on_unmount(self) -> None:
        await self._client.close()

    async def _cleanup_renderer(self, renderer: StreamRenderer) -> None:
        if await renderer.close() is not None:
            _LOGGER.warning("Discarded a secondary stream-render cleanup failure")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.query_one(PromptComposer).set_enabled(not busy)
        self.query_one(ActivityBar).set_activity(status, busy=busy)
        if not busy:
            self.query_one(PromptComposer).focus_input()
