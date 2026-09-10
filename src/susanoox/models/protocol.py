from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from susanoox.config.settings import ModelName

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    filename: str
    media_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
    data: bytes

    @property
    def display_name(self) -> str:
        cleaned = "".join(character for character in self.filename if character.isprintable())
        return cleaned.replace("`", "")[:80] or "image"


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: MessageRole
    content: str
    images: tuple[ImageAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True, slots=True)
class TextDelta:
    content: str


@dataclass(frozen=True, slots=True)
class UsageUpdate:
    usage: TokenUsage


StreamEvent: TypeAlias = TextDelta | UsageUpdate


class ChatClient(Protocol):
    async def validate_api_key(self) -> None: ...

    def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]: ...

    async def close(self) -> None: ...
