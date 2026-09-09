from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

from susanoox.models.protocol import ConversationMessage


class FakeChatClient:
    def __init__(self, *, response: tuple[str, ...] = ("Hello", " world")) -> None:
        self.response = response
        self.validated = False
        self.closed = False
        self.requests: list[tuple[ConversationMessage, ...]] = []

    async def validate_api_key(self) -> None:
        self.validated = True

    async def stream_chat(
        self, messages: Sequence[ConversationMessage]
    ) -> AsyncGenerator[str, None]:
        self.requests.append(tuple(messages))
        for chunk in self.response:
            yield chunk

    async def close(self) -> None:
        self.closed = True
