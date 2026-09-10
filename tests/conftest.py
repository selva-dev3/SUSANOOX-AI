from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

from susanoox.config.settings import ModelName
from susanoox.models.protocol import (
    ConversationMessage,
    StreamEvent,
    TextDelta,
    TokenUsage,
    UsageUpdate,
)

_DEFAULT_FAKE_USAGE = TokenUsage(prompt_tokens=3, completion_tokens=2)


class FakeChatClient:
    def __init__(
        self,
        *,
        response: tuple[str, ...] = ("Hello", " world"),
        usage: TokenUsage | None = _DEFAULT_FAKE_USAGE,
    ) -> None:
        self.response = response
        self.usage = usage
        self.validated = False
        self.closed = False
        self.requests: list[tuple[ConversationMessage, ...]] = []
        self.models: list[ModelName] = []

    async def validate_api_key(self) -> None:
        self.validated = True

    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        for chunk in self.response:
            yield TextDelta(chunk)
        if self.usage is not None:
            yield UsageUpdate(self.usage)

    async def close(self) -> None:
        self.closed = True
