from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing

from susanoox.models.protocol import ChatClient, ConversationMessage
from susanoox.utils.errors import ServiceResponseError

_SYSTEM_PROMPT = """You are Susanoox, a precise AI coding assistant.
Be concise, state uncertainty, and never claim to have inspected or changed files unless tools
have actually provided that capability. This conversation mode has no project tools enabled.
"""


class ConversationService:
    """Own multi-turn context and commit messages only after successful completion."""

    def __init__(self, client: ChatClient) -> None:
        self._client = client
        self._messages: list[ConversationMessage] = [
            ConversationMessage(role="system", content=_SYSTEM_PROMPT)
        ]

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._messages)

    async def send(self, prompt: str) -> AsyncGenerator[str, None]:
        normalized = prompt.strip()
        if not normalized:
            return
        user_message = ConversationMessage(role="user", content=normalized)
        pending = [*self._messages, user_message]
        response_parts: list[str] = []
        stream = self._client.stream_chat(pending)
        async with aclosing(stream):
            async for delta in stream:
                response_parts.append(delta)
                yield delta
        response = "".join(response_parts).strip()
        if not response:
            raise ServiceResponseError(
                "Susanoox returned an empty response. You can retry the message."
            )
        self._messages.extend(
            [user_message, ConversationMessage(role="assistant", content=response)]
        )

    def clear(self) -> None:
        del self._messages[1:]
