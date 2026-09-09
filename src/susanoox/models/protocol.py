from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: MessageRole
    content: str


class ChatClient(Protocol):
    async def validate_api_key(self) -> None: ...

    def stream_chat(self, messages: Sequence[ConversationMessage]) -> AsyncGenerator[str, None]: ...

    async def close(self) -> None: ...
