from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import aclosing
from pathlib import Path
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
from susanoox.commands import SlashCommand, UnknownCommandError, help_text, parse_slash_command
from susanoox.config.credentials import CredentialSource
from susanoox.config.settings import ModelName, Settings
from susanoox.conversations.service import ConversationService
from susanoox.models.attachments import load_image_file, read_clipboard_image
from susanoox.models.catalog import get_model
from susanoox.models.protocol import ChatClient, ImageAttachment
from susanoox.ui.screens.model_picker import ModelPickerScreen
from susanoox.ui.streaming import StreamRenderer, cancelled_content
from susanoox.ui.widgets.activity import ActivityBar
from susanoox.ui.widgets.header import AppHeader
from susanoox.ui.widgets.logo import susanoox_mark
from susanoox.ui.widgets.messages import ConversationView, MessageKind
from susanoox.ui.widgets.prompt import PromptComposer, PromptInput
from susanoox.utils.errors import AttachmentError, AuthenticationError, SusanooxError

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
        Binding("ctrl+k", "clear", "Clear"),
        Binding("ctrl+shift+v", "paste_image", "Paste image"),
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
        self._active_model: ModelName = settings.model
        self._attachment_generation = 0
        self._attachment_loading = False
        self._local_generation = 0
        self._local_render_lock = asyncio.Lock()

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
                            yield Static(susanoox_mark(), id="welcome-mark")
                            yield Static(
                                Text(
                                    f"{self._active_model}  ·  {self._settings.project_path.name}"
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
                        "Enter to send  ·  Shift+Enter for a new line  ·  /help for commands",
                        id="welcome-hint",
                    )
            yield ActivityBar(id="activity-bar")
            yield PromptComposer(id="prompt-composer")
            yield Static(
                "Enter send  ·  Shift+Enter newline  ·  Ctrl+Shift+V image  ·  Esc cancel",
                id="shortcut-bar",
            )

    def on_mount(self) -> None:
        self.query_one(PromptComposer).focus_input()

    @on(Button.Pressed, "#send-button")
    def send_button_pressed(self) -> None:
        self.action_submit()

    @on(PromptInput.Submitted)
    def prompt_submitted(self) -> None:
        self.action_submit()

    @on(Button.Pressed, "#attachment-button")
    def remove_attachment(self) -> None:
        self._invalidate_attachment_load()
        composer = self.query_one(PromptComposer)
        composer.clear_attachment()
        composer.focus_input()

    @on(PromptInput.ImagePathPasted)
    def image_path_pasted(self, event: PromptInput.ImagePathPasted) -> None:
        self.load_path_attachment(event.path)

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
        attachment = composer.attachment
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        if self._attachment_loading:
            self.query_one(ActivityBar).set_activity("Loading image…", busy=True)
            return
        if attachment is not None and not self._image_allowed():
            return
        try:
            command = parse_slash_command(prompt)
        except UnknownCommandError as error:
            composer.clear()
            self.show_local_message(str(error), kind="error")
            return
        if command is not None:
            if attachment is not None:
                self.show_local_message("Remove the image before running a command.", kind="error")
                return
            composer.clear()
            self._run_command(command)
            return
        if not prompt and attachment is None:
            return
        composer.clear()
        composer.clear_attachment()
        self._chat_worker = self.stream_response(prompt, attachment)

    @work(exclusive=True, group="chat")
    async def stream_response(self, prompt: str, attachment: ImageAttachment | None = None) -> None:
        view = self.query_one(ConversationView)
        self.query_one("#welcome-panel").display = False
        normalized_prompt = prompt or "Describe this image."
        displayed_prompt = normalized_prompt
        if attachment is not None:
            displayed_prompt = f"{normalized_prompt}\n\n📎 `{attachment.display_name}`"
        await view.add_message(displayed_prompt, kind="user")
        assistant_message = await view.add_message("", kind="assistant")
        self._set_busy(True, "Thinking…")
        renderer = StreamRenderer(interval_seconds=_STREAM_RENDER_INTERVAL_SECONDS)
        response_committed = False
        try:
            images = (attachment,) if attachment is not None else ()
            response_stream = self._conversation.send(
                normalized_prompt,
                model=self._active_model,
                images=images,
            )
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
        if self._attachment_loading:
            self._invalidate_attachment_load()
            self.query_one(ActivityBar).set_activity("Image loading cancelled", busy=False)
        if self._chat_worker is not None and self._chat_worker.is_running:
            self._chat_worker.cancel()

    def action_paste_image(self) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        self.load_clipboard_attachment()

    def load_path_attachment(self, path: Path) -> None:
        self._start_attachment_load(lambda: load_image_file(path))

    def load_clipboard_attachment(self) -> None:
        self._start_attachment_load(read_clipboard_image)

    def _start_attachment_load(self, loader: Callable[[], ImageAttachment]) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        if not self._image_allowed():
            return
        self._attachment_generation += 1
        self._attachment_loading = True
        self.query_one(ActivityBar).set_activity("Loading image…", busy=True)
        self._load_attachment(loader, self._attachment_generation)

    @work(exclusive=True, group="attachment")
    async def _load_attachment(
        self, loader: Callable[[], ImageAttachment], generation: int
    ) -> None:
        try:
            attachment = await asyncio.to_thread(loader)
        except AttachmentError as error:
            if generation == self._attachment_generation and self.is_mounted:
                self._attachment_failed(str(error))
        except Exception:
            _LOGGER.warning("Image loader failed unexpectedly")
            if generation == self._attachment_generation and self.is_mounted:
                self._attachment_failed("Could not read image. Try an image file path.")
        else:
            if generation == self._attachment_generation and self.is_mounted:
                self._attachment_loaded(attachment)
        finally:
            if generation == self._attachment_generation:
                self._attachment_loading = False

    def _invalidate_attachment_load(self) -> None:
        self._attachment_generation += 1
        self._attachment_loading = False
        self.workers.cancel_group(self, "attachment")  # pyright: ignore[reportUnknownMemberType]

    def _image_allowed(self) -> bool:
        model = get_model(self._active_model)
        if model is None or not model.supports_chat or model.supports_images is False:
            self.query_one(ActivityBar).set_activity(
                "This model does not support image input. Select another with /model.", busy=False
            )
            return False
        return True

    def _attachment_loaded(self, attachment: ImageAttachment) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        self.query_one(PromptComposer).set_attachment(attachment)
        model = get_model(self._active_model)
        status = "Image attached"
        if model is not None and model.supports_images is None:
            status += " · image understanding depends on deployment support (unverified)"
        self.query_one(ActivityBar).set_activity(status, busy=False)
        self.query_one(PromptComposer).focus_input()

    def _attachment_failed(self, message: str) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        self.query_one(ActivityBar).set_activity(f"Image not attached · {message}", busy=False)
        self.query_one(PromptComposer).focus_input()

    def _run_command(self, command: SlashCommand) -> None:
        if command.name == "model":
            if command.argument is None:
                app = cast(
                    "SusanooxApp",
                    self.app,  # pyright: ignore[reportUnknownMemberType]
                )
                app.push_screen(
                    ModelPickerScreen(current_model=self._active_model),
                    self._model_selected,
                )
            else:
                model = get_model(command.argument)
                if model is None:
                    self.show_local_message(
                        f"Unknown model: {command.argument}. Type /model to see available models.",
                        kind="error",
                    )
                elif not model.supports_chat:
                    self.show_local_message(
                        f"{model.name} is for embeddings and cannot be used for conversation.",
                        kind="error",
                    )
                else:
                    self._model_selected(model.name)
        elif command.name == "usage":
            self.show_local_message(self._usage_text())
        elif command.name == "paste-image":
            self.action_paste_image()
        elif command.name == "help":
            self.show_local_message(help_text())
        elif command.name == "clear":
            self.action_clear()
        elif command.name == "exit":
            self.action_quit()

    def _model_selected(self, model: ModelName | None) -> None:
        if model is None:
            self.query_one(PromptComposer).focus_input()
            return
        self._active_model = model
        self.query_one(AppHeader).set_model(model)
        context = self.query_one("#welcome-context", Static)
        context.update(Text(f"{model}  ·  {self._settings.project_path.name}"))
        self._set_busy(False, f"Model selected · {model}")

    def _usage_text(self) -> str:
        usage = self._conversation.usage
        missing = self._conversation.unaccounted_requests
        if missing and not self._conversation.usage_by_model:
            return (
                "**Session usage unavailable**\n\n"
                f"{missing} request(s) have no usage metadata, including possible interruptions."
            )
        lines = [
            "**Session usage**",
            "",
            f"Prompt: {usage.prompt_tokens:,} tokens",
            f"Completion: {usage.completion_tokens:,} tokens",
            f"Total: {usage.total_tokens:,} tokens",
        ]
        for model, model_usage in self._conversation.usage_by_model:
            lines.append(f"- `{model}`: {model_usage.total_tokens:,}")
        if missing:
            lines[0] = "**Partial session usage — reported tokens only**"
            lines.append(
                f"\n{missing} request(s) have unknown usage; the session total is incomplete."
            )
        return "\n".join(lines)

    def show_local_message(self, content: str, *, kind: MessageKind = "assistant") -> Worker[None]:
        return self._render_local_message(content, kind, self._local_generation)

    @work(group="local-message")
    async def _render_local_message(self, content: str, kind: MessageKind, generation: int) -> None:
        async with self._local_render_lock:
            if generation != self._local_generation:
                return
            view = self.query_one(ConversationView)
            message = await view.add_message(content, kind=kind)
            if generation != self._local_generation:
                await message.remove()
                return
            self.query_one("#welcome-panel").display = False

    def action_clear(self) -> None:
        if self._chat_worker is not None and self._chat_worker.is_running:
            return
        self._local_generation += 1
        self._invalidate_attachment_load()
        self.query_one(PromptComposer).clear_attachment()
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
        self._local_generation += 1
        self._invalidate_attachment_load()
        await self._client.close()

    async def _cleanup_renderer(self, renderer: StreamRenderer) -> None:
        if await renderer.close() is not None:
            _LOGGER.warning("Discarded a secondary stream-render cleanup failure")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.query_one(PromptComposer).set_enabled(not busy)
        self.query_one(ActivityBar).set_activity(status, busy=busy)
        if not busy:
            self.query_one(PromptComposer).focus_input()
