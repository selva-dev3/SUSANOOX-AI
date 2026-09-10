from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import replace
from typing import Final

from susanoox.config.settings import ModelName
from susanoox.models.protocol import (
    ChatClient,
    ConversationMessage,
    ImageAttachment,
    TextDelta,
    TokenUsage,
)
from susanoox.utils.errors import ServiceResponseError

_SYSTEM_PROMPT = """You are Susanoox, a precise AI coding assistant.
Be concise, state uncertainty, and never claim to have inspected or changed files unless tools
have actually provided that capability. This conversation mode has no project tools enabled.
"""
MAX_CONTEXT_IMAGE_BYTES: Final = 20 * 1024 * 1024


class ConversationService:
    """Own multi-turn context and commit messages only after successful completion."""

    def __init__(self, client: ChatClient) -> None:
        self._client = client
        self._messages: list[ConversationMessage] = [
            ConversationMessage(role="system", content=_SYSTEM_PROMPT)
        ]
        self._usage_by_model: dict[ModelName, TokenUsage] = {}
        self._completed_requests = 0
        self._unaccounted_requests = 0

    def replace_client(self, client: ChatClient) -> None:
        """Rebind preserved conversation state after authentication renewal."""
        self._client = client

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

    async def send(
        self,
        prompt: str,
        *,
        model: ModelName,
        images: tuple[ImageAttachment, ...] = (),
    ) -> AsyncGenerator[str, None]:
        normalized = prompt.strip()
        if not normalized and not images:
            return
        if not normalized:
            normalized = "Describe this image."
        user_message = ConversationMessage(role="user", content=normalized, images=images)
        pending = self._apply_image_budget([*self._messages, user_message])
        response_parts: list[str] = []
        request_usage: TokenUsage | None = None
        stream = self._client.stream_chat(pending, model=model)
        try:
            async with aclosing(stream):
                async for event in stream:
                    if isinstance(event, TextDelta):
                        response_parts.append(event.content)
                        yield event.content
                    else:
                        request_usage = event.usage
        finally:
            if request_usage is None:
                self._unaccounted_requests += 1
            else:
                self._usage_by_model[model] = (
                    self._usage_by_model.get(model, TokenUsage()) + request_usage
                )
        response = "".join(response_parts).strip()
        if not response:
            raise ServiceResponseError(
                "Susanoox returned an empty response. You can retry the message."
            )
        self._completed_requests += 1
        self._messages = [
            *pending,
            ConversationMessage(role="assistant", content=response),
        ]

    def clear(self) -> None:
        del self._messages[1:]

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
