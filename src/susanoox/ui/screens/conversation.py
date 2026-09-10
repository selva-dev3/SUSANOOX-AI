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
from susanoox.agent.planner import PlanService
from susanoox.agent.retry import RetryPolicy
from susanoox.agent.types import AgentEvent, ExecutionPlan, PlanStatus
from susanoox.commands import SlashCommand, UnknownCommandError, help_text, parse_slash_command
from susanoox.config.credentials import CredentialSource
from susanoox.config.settings import ModelName, Settings
from susanoox.context.models import ContextSnapshot
from susanoox.context.selector import ContextSelector
from susanoox.conversations.service import ConversationService
from susanoox.models.attachments import load_image_file, read_clipboard_image
from susanoox.models.catalog import get_model
from susanoox.models.protocol import ChatClient, ImageAttachment
from susanoox.project.detector import detect_project
from susanoox.sessions.storage import SessionStore
from susanoox.summarization.service import ConversationSummarizer
from susanoox.ui.screens.model_picker import ModelPickerScreen
from susanoox.ui.streaming import StreamRenderer, cancelled_content
from susanoox.ui.widgets.activity import ActivityBar
from susanoox.ui.widgets.command_suggestions import CommandSuggestions
from susanoox.ui.widgets.header import AppHeader
from susanoox.ui.widgets.logo import susanoox_mark
from susanoox.ui.widgets.messages import ConversationView, MessageKind
from susanoox.ui.widgets.prompt import PromptComposer, PromptInput
from susanoox.utils.errors import AttachmentError, AuthenticationError, SessionError, SusanooxError

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
        session_store: SessionStore | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._client = client
        project = detect_project(settings.project_path)
        self._context_selector = (
            ContextSelector(
                project,
                max_files=settings.context_max_files,
                max_chars=settings.context_max_chars,
                max_file_bytes=settings.context_max_file_bytes,
            )
            if settings.auto_context
            else None
        )
        self._conversation = ConversationService(
            client,
            context_selector=self._context_selector,
            summarizer=ConversationSummarizer(
                trigger_chars=settings.summary_trigger_chars,
                recent_messages=settings.summary_recent_messages,
            ),
            retry_policy=RetryPolicy(
                max_attempts=settings.api_retry_attempts,
                base_delay_seconds=settings.retry_base_delay_seconds,
            ),
            session_store=session_store,
            session_id=session_id,
            on_event=self._agent_event,
        )
        self._session_store = session_store
        self._plan_service = PlanService()
        self._current_plan: ExecutionPlan | None = (
            session_store.latest_plan(self._conversation.session_id) if session_store else None
        )
        self._plan_context: ContextSnapshot | None = (
            session_store.load_context_metadata(self._current_plan.context_snapshot_id)
            if session_store
            and self._current_plan is not None
            and self._current_plan.context_snapshot_id is not None
            else None
        )
        self._plan_mode = settings.plan_mode
        self._credential_source = credential_source
        self._chat_worker: Worker[None] | None = None
        self._plan_worker: Worker[None] | None = None
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
            yield CommandSuggestions()
            yield PromptComposer(id="prompt-composer")
            yield Static(
                "Enter send  ·  Shift+Enter newline  ·  Ctrl+Shift+V image  ·  Esc cancel",
                id="shortcut-bar",
            )

    def on_mount(self) -> None:
        self.query_one(PromptComposer).focus_input()
        if len(self._conversation.messages) > 1 or (
            self._current_plan is not None
            and self._current_plan.status is PlanStatus.AWAITING_APPROVAL
        ):
            self._restore_messages()
        if self._plan_mode:
            self.query_one(ActivityBar).set_activity("Plan mode · describe a task", busy=False)

    @work(group="session-restore")
    async def _restore_messages(self) -> None:
        view = self.query_one(ConversationView)
        self.query_one("#welcome-panel").display = False
        for message in self._conversation.messages[1:]:
            if message.role == "user":
                await view.add_message(message.content, kind="user")
            elif message.role == "assistant":
                await view.add_message(message.content, kind="assistant")
        if (
            self._current_plan is not None
            and self._current_plan.status is PlanStatus.AWAITING_APPROVAL
        ):
            await view.add_message(self._plan_service.render(self._current_plan), kind="assistant")
            self._set_busy(False, "Plan ready · awaiting approval")

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
        if self._plan_mode and attachment is None:
            self._plan_worker = self._create_plan(prompt)
            return
        self._chat_worker = self.stream_response(prompt, attachment)

    @work(exclusive=True, group="chat")
    async def stream_response(
        self,
        prompt: str,
        attachment: ImageAttachment | None = None,
        context_snapshot: ContextSnapshot | None = None,
    ) -> None:
        view = self.query_one(ConversationView)
        self.query_one("#welcome-panel").display = False
        normalized_prompt = prompt or "Describe this image."
        displayed_prompt = normalized_prompt
        if attachment is not None:
            displayed_prompt = f"{normalized_prompt}\n\n📎 `{attachment.display_name}`"
        await view.add_message(displayed_prompt, kind="user")
        if context_snapshot is None and self._context_selector is not None and attachment is None:
            self._set_busy(True, "Selecting project context…")
            try:
                context_snapshot = await asyncio.to_thread(
                    self._context_selector.select, normalized_prompt
                )
            except asyncio.CancelledError:
                if self.is_mounted:
                    self._set_busy(False, "Cancelled")
                raise
            except Exception as error:
                _LOGGER.warning("Automatic context selection failed (%s)", type(error).__name__)
                if self.is_mounted:
                    await view.add_message(
                        "Automatic project context could not be selected; "
                        "the request was not sent.",
                        kind="error",
                    )
                    self._set_busy(False, "Context selection failed")
                return
        if context_snapshot is not None and context_snapshot.files:
            selected = "  ·  ".join(f"`{item.path}`" for item in context_snapshot.files)
            await view.add_message(selected, kind="activity")
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
                context_snapshot=context_snapshot,
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
            app = cast(
                "SusanooxApp",
                self.app,  # pyright: ignore[reportUnknownMemberType]
            )
            if app.is_running and self.is_running and assistant_message.is_attached:
                content = (
                    renderer.content if response_committed else cancelled_content(renderer.content)
                )
                try:
                    await assistant_message.update_content(content)
                    self._set_busy(False, "Ready" if response_committed else "Cancelled")
                except Exception:
                    _LOGGER.warning("Unable to render cancellation status during cleanup")
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

    @work(exclusive=True, group="planning")
    async def _create_plan(self, objective: str) -> None:
        self._set_busy(True, "Planning…")
        context = None
        try:
            if self._context_selector is not None:
                self._agent_event(
                    AgentEvent(kind="context_started", message="Selecting project context")
                )
                context = await asyncio.to_thread(self._context_selector.select, objective)
            self._plan_context = context
            version = self._current_plan.version + 1 if self._current_plan else 1
            self._current_plan = self._plan_service.create(
                session_id=self._conversation.session_id,
                objective=objective,
                context=context,
                version=version,
            )
            if self._session_store is not None:
                if context is not None:
                    await asyncio.to_thread(
                        self._session_store.save_context_metadata,
                        self._conversation.session_id,
                        context,
                    )
                await asyncio.to_thread(self._session_store.save_plan, self._current_plan)
            self.show_local_message(self._plan_service.render(self._current_plan))
            self._set_busy(False, "Plan ready · awaiting approval")
        except SusanooxError as error:
            self.show_local_message(str(error), kind="error")
            self._set_busy(False, "Planning failed")
        except Exception as error:
            _LOGGER.warning("Unexpected planning failure (%s)", type(error).__name__)
            self.show_local_message(
                "The plan could not be created because of an unexpected local error.",
                kind="error",
            )
            self._set_busy(False, "Planning failed")

    def action_cancel(self) -> None:
        if self._attachment_loading:
            self._invalidate_attachment_load()
            self.query_one(ActivityBar).set_activity("Image loading cancelled", busy=False)
        if self._chat_worker is not None and self._chat_worker.is_running:
            self._chat_worker.cancel()
        if self._plan_worker is not None and self._plan_worker.is_running:
            self._plan_worker.cancel()
            if self.is_mounted:
                self._set_busy(False, "Planning cancelled")

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
        elif command.name == "plan":
            if command.argument:
                self._plan_worker = self._create_plan(command.argument)
            else:
                self._plan_mode = not self._plan_mode
                state = "enabled" if self._plan_mode else "disabled"
                self.show_local_message(f"Plan mode **{state}**.")
                self._set_busy(False, f"Plan mode {state}")
        elif command.name == "approve":
            self._plan_worker = self._approve_plan()
        elif command.name == "revise":
            self._plan_worker = self._revise_plan(command.argument)
        elif command.name == "reject":
            self._reject_plan()
        elif command.name == "context":
            self.show_local_message(self._context_text())
        elif command.name == "help":
            self.show_local_message(help_text())
        elif command.name == "clear":
            self.action_clear()
        elif command.name == "exit":
            self.action_quit()

    @work(exclusive=True, group="planning")
    async def _approve_plan(self) -> None:
        if self._current_plan is None:
            self.show_local_message("There is no plan awaiting approval.", kind="error")
            return
        try:
            await self._refresh_plan_context(self._current_plan.objective)
            self._current_plan = self._plan_service.approve(self._current_plan)
        except SusanooxError as error:
            self.show_local_message(str(error), kind="error")
            self._set_busy(False, "Plan approval failed")
            return
        except Exception as error:
            _LOGGER.warning("Plan approval failed (%s)", type(error).__name__)
            self.show_local_message(
                "The plan could not be approved because its context could not be refreshed.",
                kind="error",
            )
            self._set_busy(False, "Plan approval failed")
            return
        self._persist_plan(self._current_plan)
        objective = self._current_plan.objective
        steps = "\n".join(f"{step.ordinal}. {step.title}" for step in self._current_plan.steps)
        self._plan_mode = False
        self.show_local_message(
            "Plan approved. Sending the task and visible plan to the conversation model."
        )
        self._chat_worker = self.stream_response(
            f"Use this approved visible plan to guide your response to the task. "
            f"Do not claim to execute unavailable tools.\n\nTask:\n{objective}\n\nPlan:\n{steps}",
            context_snapshot=(
                self._plan_context
                if self._plan_context is not None and self._plan_context.total_chars > 0
                else None
            ),
        )

    @work(exclusive=True, group="planning")
    async def _revise_plan(self, feedback: str | None) -> None:
        if self._current_plan is None:
            self.show_local_message("There is no plan to revise.", kind="error")
            return
        try:
            revised_objective = self._plan_service.revision_objective(
                self._current_plan, feedback or ""
            )
            await self._refresh_plan_context(revised_objective, force=True)
            self._current_plan = self._plan_service.revise(
                self._current_plan,
                feedback or "",
                context=self._plan_context,
            )
        except SusanooxError as error:
            self.show_local_message(str(error), kind="error")
            self._set_busy(False, "Plan revision failed")
            return
        except Exception as error:
            _LOGGER.warning("Plan revision failed (%s)", type(error).__name__)
            self.show_local_message(
                "The plan could not be revised because its context could not be refreshed.",
                kind="error",
            )
            self._set_busy(False, "Plan revision failed")
            return
        self._persist_plan(self._current_plan)
        self.show_local_message(self._plan_service.render(self._current_plan))
        self._set_busy(False, "Revised plan ready · awaiting approval")

    async def _refresh_plan_context(self, objective: str, *, force: bool = False) -> None:
        if self._context_selector is None:
            return
        if not force and self._plan_context is not None and self._plan_context.total_chars > 0:
            return
        self._set_busy(True, "Refreshing plan context…")
        context = await asyncio.to_thread(self._context_selector.select, objective)
        self._plan_context = context
        if self._current_plan is not None:
            self._current_plan = self._current_plan.model_copy(
                update={"context_snapshot_id": context.id}
            )
        if self._session_store is not None:
            await asyncio.to_thread(
                self._session_store.save_context_metadata,
                self._conversation.session_id,
                context,
            )

    def _reject_plan(self) -> None:
        if self._current_plan is None:
            self.show_local_message("There is no plan awaiting approval.", kind="error")
            return
        try:
            self._current_plan = self._plan_service.reject(self._current_plan)
        except SusanooxError as error:
            self.show_local_message(str(error), kind="error")
            return
        self._persist_plan(self._current_plan)
        self._plan_mode = False
        self.show_local_message("Plan cancelled. No execution was started.")
        self._set_busy(False, "Ready")

    def _context_text(self) -> str:
        snapshot = self._conversation.last_context or self._plan_context
        if snapshot is None or not snapshot.files:
            return "**◆ CONTEXT**\n\nNo files were selected for the last request."
        lines = ["**◆ CONTEXT**", ""]
        lines.extend(f"- ✓ `{item.path}` — {', '.join(item.reasons)}" for item in snapshot.files)
        lines.append(f"\n{snapshot.total_chars:,} characters selected within the context budget.")
        return "\n".join(lines)

    def _agent_event(self, event: AgentEvent) -> None:
        labels = {
            "context_started": "Selecting project context…",
            "context_ready": event.message,
            "summarizing": "Compacting conversation context…",
            "summary_ready": "Previous discussion summarized",
            "retrying": f"↻ {event.message}",
            "failed": event.message,
        }
        label = labels.get(event.kind)
        if label is not None and self.is_mounted:
            self.query_one(ActivityBar).set_activity(
                label,
                busy=event.kind in {"context_started", "context_ready", "summarizing", "retrying"},
            )

    def _persist_plan(self, plan: ExecutionPlan) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.save_plan(plan)
        except SessionError:
            _LOGGER.warning("Execution plan could not be persisted")
            self.show_local_message(
                "The plan state changed, but this session could not be saved.", kind="error"
            )

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
        try:
            self._conversation.clear()
        except SessionError:
            self.show_local_message(
                "The conversation was cleared in memory, but session storage could not be updated.",
                kind="error",
            )
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
