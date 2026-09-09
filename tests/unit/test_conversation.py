from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from susanoox.conversations.service import ConversationService
from susanoox.models.protocol import ConversationMessage
from susanoox.utils.errors import ServiceResponseError
from tests.conftest import FakeChatClient


class BlockingChatClient(FakeChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.stream_closed = False

    async def stream_chat(
        self, messages: Sequence[ConversationMessage]
    ) -> AsyncGenerator[str, None]:
        self.requests.append(tuple(messages))
        try:
            yield "partial"
            self.started.set()
            await asyncio.Event().wait()
        finally:
            self.stream_closed = True


async def test_conversation_retains_successful_multi_turn_context() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)

    first = "".join([chunk async for chunk in conversation.send("First question")])
    second = "".join([chunk async for chunk in conversation.send("Follow-up")])

    assert first == "Hello world"
    assert second == "Hello world"
    assert [message.content for message in client.requests[1]] == [
        conversation.messages[0].content,
        "First question",
        "Hello world",
        "Follow-up",
    ]


async def test_cancelled_exchange_is_not_committed_to_model_context() -> None:
    client = BlockingChatClient()
    conversation = ConversationService(client)

    async def consume() -> None:
        async for _chunk in conversation.send("Cancelled prompt"):
            pass

    task = asyncio.create_task(consume())
    await client.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(conversation.messages) == 1
    assert client.stream_closed


async def test_empty_response_is_retryable_and_not_committed() -> None:
    conversation = ConversationService(FakeChatClient(response=(" ", "\n")))

    with pytest.raises(ServiceResponseError, match="retry"):
        _ = [part async for part in conversation.send("Prompt")]

    assert len(conversation.messages) == 1
