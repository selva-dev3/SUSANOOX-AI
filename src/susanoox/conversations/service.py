from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import replace
from typing import Final
from uuid import uuid4

from susanoox.agent.retry import RetryPolicy, collect_with_retry
from susanoox.agent.types import AgentEvent, AttemptRecord
from susanoox.config.settings import ModelName
from susanoox.context.models import ContextFile, ContextSnapshot
from susanoox.context.selector import ContextSelector
from susanoox.models.protocol import (
    ChatClient,
    ConversationMessage,
    ImageAttachment,
    StreamEvent,
    TextDelta,
    TokenUsage,
)
from susanoox.sessions.storage import SessionStore
from susanoox.summarization.models import ConversationSummary
from susanoox.summarization.service import ConversationSummarizer
from susanoox.utils.errors import (
    ContextOverflowError,
    ModelOutputError,
    ServiceResponseError,
    SessionError,
)

_SYSTEM_PROMPT = """You are Susanoox, a precise AI coding assistant.
Be concise, state uncertainty, and never claim to have inspected or changed files unless tools
have actually provided that capability. This conversation mode has no project tools enabled.
"""
MAX_CONTEXT_IMAGE_BYTES: Final = 20 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


class ConversationService:
    """Own multi-turn context and commit messages only after successful completion."""

    def __init__(
        self,
        client: ChatClient,
        *,
        context_selector: ContextSelector | None = None,
        summarizer: ConversationSummarizer | None = None,
        retry_policy: RetryPolicy | None = None,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self._client = client
        self._context_selector = context_selector
        self._summarizer = summarizer
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=0)
        self._session_store = session_store
        self.session_id = session_id or str(uuid4())
        self._on_event = on_event
        loaded = session_store.load_messages(self.session_id) if session_store else ()
        system_message = ConversationMessage(role="system", content=_SYSTEM_PROMPT)
        self._messages: list[ConversationMessage] = (
            [system_message, *loaded[1:]] if loaded else [system_message]
        )
        self._summary: ConversationSummary | None = (
            session_store.load_summary(self.session_id) if session_store else None
        )
        if self._summary is not None and self._summary.covered_message_count > len(self._messages):
            raise SessionError("Stored conversation summary is newer than its message history.")
        self._last_context: ContextSnapshot | None = None
        self._usage_by_model: dict[ModelName, TokenUsage] = (
            session_store.load_usage(self.session_id) if session_store else {}
        )
        self._messages_persisted = True
        self._completed_requests = sum(message.role == "assistant" for message in loaded)
        self._unaccounted_requests = 0

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._messages)

    @property
    def usage(self) -> TokenUsage:
        total = TokenUsage()
        for usage in self._usage_by_model.values():
            total += usage
        return total

    @property
    def usage_by_model(self) -> tuple[tuple[ModelName, TokenUsage], ...]:
        return tuple(self._usage_by_model.items())

    @property
    def completed_requests(self) -> int:
        return self._completed_requests

    @property
    def unaccounted_requests(self) -> int:
        return self._unaccounted_requests

    @property
    def summary(self) -> ConversationSummary | None:
        return self._summary

    @property
    def last_context(self) -> ContextSnapshot | None:
        return self._last_context

    async def send(
        self,
        prompt: str,
        *,
        model: ModelName,
        images: tuple[ImageAttachment, ...] = (),
        context_snapshot: ContextSnapshot | None = None,
    ) -> AsyncGenerator[str, None]:
        normalized = prompt.strip()
        if not normalized and not images:
            return
        if not normalized:
            normalized = "Describe this image."
        user_message = ConversationMessage(role="user", content=normalized, images=images)
        await self._prepare_summary(persist=self._messages_persisted)
        request_messages = self._reconstructed_messages()
        active_context: ContextSnapshot | None = None
        if context_snapshot is not None:
            self._last_context = context_snapshot
            if context_snapshot.files:
                active_context = context_snapshot
                request_messages.append(
                    ConversationMessage(role="system", content=context_snapshot.as_system_context())
                )
            self._emit(
                AgentEvent(
                    kind="context_ready",
                    message=f"Reused {len(context_snapshot.files)} planned project file(s)",
                    current=len(context_snapshot.files),
                    total=len(context_snapshot.files) + context_snapshot.omitted_files,
                )
            )
        elif self._context_selector is not None and not images:
            self._emit(AgentEvent(kind="context_started", message="Selecting project context"))
            self._last_context = await asyncio.to_thread(self._context_selector.select, normalized)
            if self._last_context.files:
                active_context = self._last_context
                request_messages.append(
                    ConversationMessage(
                        role="system",
                        content=self._last_context.as_system_context(),
                    )
                )
            self._emit(
                AgentEvent(
                    kind="context_ready",
                    message=f"Selected {len(self._last_context.files)} relevant project file(s)",
                    current=len(self._last_context.files),
                    total=len(self._last_context.files) + self._last_context.omitted_files,
                )
            )
        pending = self._apply_image_budget([*request_messages, user_message])
        response_parts: list[str] = []
        request_usage: TokenUsage | None = None

        async def create_stream() -> AsyncGenerator[StreamEvent, None]:
            has_text = False
            client_stream = self._client.stream_chat(pending, model=model)
            async with aclosing(client_stream):
                async for event in client_stream:
                    if isinstance(event, TextDelta) and event.content.strip():
                        has_text = True
                    yield event
            if not has_text:
                raise ModelOutputError(
                    "Susanoox returned an empty response. You can retry the message."
                )

        async def before_retry(error: Exception, retry_number: int) -> None:
            nonlocal active_context, pending
            decision = self._retry_policy.classify(error)
            if isinstance(error, ContextOverflowError):
                self._summary = self._force_compact()
                rebuilt = self._reconstructed_messages()
                if active_context is not None and active_context.files:
                    active_context = self._reduce_context(active_context)
                    rebuilt.append(
                        ConversationMessage(
                            role="system",
                            content=active_context.as_system_context(),
                        )
                    )
                pending = self._apply_image_budget([*rebuilt, user_message])
            if self._session_store is not None:
                attempt = AttemptRecord(
                    session_id=self.session_id,
                    action="stream_chat",
                    category=decision.category,
                    attempt=retry_number,
                    max_attempts=decision.max_attempts,
                    fingerprint=self._retry_policy.fingerprint(
                        "stream_chat", decision.category, str(len(self._messages))
                    ),
                )
                try:
                    await asyncio.to_thread(self._session_store.add_attempt, attempt)
                except SessionError:
                    _LOGGER.warning("Retry metadata could not be persisted")
            self._emit(
                AgentEvent(
                    kind="retrying",
                    message=f"Retrying after {decision.category}",
                    current=retry_number,
                    total=decision.max_attempts,
                )
            )

        stream = collect_with_retry(
            create_stream,
            self._retry_policy,
            before_retry,
            is_visible=lambda event: isinstance(event, TextDelta) and bool(event.content.strip()),
        )
        try:
            async with aclosing(stream):
                async for event, _retry_number in stream:
                    if isinstance(event, TextDelta):
                        response_parts.append(event.content)
                        yield event.content
                    else:
                        request_usage = (request_usage or TokenUsage()) + event.usage
        finally:
            if request_usage is None:
                self._unaccounted_requests += 1
            else:
                self._usage_by_model[model] = (
                    self._usage_by_model.get(model, TokenUsage()) + request_usage
                )
            if self._session_store is not None and request_usage is not None:
                try:
                    self._session_store.save_usage(self.session_id, self._usage_by_model)
                except SessionError:
                    _LOGGER.warning("Token usage could not be persisted")
        response = "".join(response_parts).strip()
        if not response:
            raise ServiceResponseError(
                "Susanoox returned an empty response. You can retry the message."
            )
        self._completed_requests += 1
        self._messages = self._apply_image_budget(
            [
                *self._messages,
                user_message,
                ConversationMessage(role="assistant", content=response),
            ]
        )
        self._messages_persisted = self._session_store is None
        messages_persisted = self._session_store is None
        if self._session_store is not None:
            try:
                await asyncio.to_thread(
                    self._session_store.save_messages,
                    self.session_id,
                    self._messages,
                )
                if self._completed_requests == 1:
                    await asyncio.to_thread(
                        self._session_store.rename,
                        self.session_id,
                        normalized[:80],
                    )
                messages_persisted = True
                self._messages_persisted = True
            except SessionError:
                _LOGGER.warning("Completed response could not be persisted")
                self._emit(
                    AgentEvent(
                        kind="failed",
                        message="Response complete, but this session could not be saved",
                    )
                )
        await self._prepare_summary(persist=messages_persisted)

    def clear(self) -> None:
        del self._messages[1:]
        self._summary = None
        self._last_context = None
        if self._session_store is not None:
            self._session_store.save_messages(self.session_id, self._messages)
            self._session_store.clear_summary(self.session_id)
        self._messages_persisted = True

    def _reconstructed_messages(self) -> list[ConversationMessage]:
        if self._summarizer is None:
            return list(self._messages)
        return self._summarizer.reconstruct(self._messages, self._summary)

    async def _prepare_summary(self, *, persist: bool = True) -> None:
        if self._summarizer is None or not self._summarizer.needs_compaction(
            self._messages, self._summary
        ):
            return
        self._emit(AgentEvent(kind="summarizing", message="Compacting conversation context"))
        self._summary = self._summarizer.compact(self._messages, self._summary)
        if self._session_store is not None and persist:
            try:
                await asyncio.to_thread(
                    self._session_store.save_summary, self.session_id, self._summary
                )
            except SessionError:
                _LOGGER.warning("Conversation summary could not be persisted")
        self._emit(AgentEvent(kind="summary_ready", message="Previous discussion summarized"))

    def _force_compact(self) -> ConversationSummary | None:
        if self._summarizer is None:
            return None
        summary = self._summarizer.compact(
            self._messages,
            self._summary,
            recent_messages=2,
        )
        return summary

    def _emit(self, event: AgentEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)

    @staticmethod
    def _reduce_context(snapshot: ContextSnapshot) -> ContextSnapshot:
        """Retain a bounded portion of selected context for overflow recovery."""
        target = max(500, snapshot.total_chars // 2)
        remaining = target
        files: list[ContextFile] = []
        for item in snapshot.files:
            if remaining <= 0:
                break
            excerpt = item.excerpt[:remaining]
            if excerpt:
                files.append(
                    item.model_copy(
                        update={
                            "excerpt": excerpt,
                            "truncated": item.truncated or len(excerpt) < len(item.excerpt),
                        }
                    )
                )
                remaining -= len(excerpt)
        return snapshot.model_copy(
            update={
                "files": tuple(files),
                "omitted_files": snapshot.omitted_files + len(snapshot.files) - len(files),
                "total_chars": sum(len(item.excerpt) for item in files),
            }
        )

    @staticmethod
    def _apply_image_budget(
        messages: list[ConversationMessage],
    ) -> list[ConversationMessage]:
        remaining = MAX_CONTEXT_IMAGE_BYTES
        newest_first: list[ConversationMessage] = []
        for message in reversed(messages):
            image_bytes = sum(len(image.data) for image in message.images)
            if image_bytes > remaining:
                newest_first.append(replace(message, images=()))
            else:
                newest_first.append(message)
                remaining -= image_bytes
        return list(reversed(newest_first))
