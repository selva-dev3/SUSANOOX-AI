from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from susanoox.config.settings import ModelName
from susanoox.conversations.service import MAX_CONTEXT_IMAGE_BYTES, ConversationService
from susanoox.models.protocol import ConversationMessage, ImageAttachment, StreamEvent, TextDelta
from susanoox.utils.errors import ServiceResponseError
from tests.conftest import FakeChatClient


class BlockingChatClient(FakeChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.stream_closed = False

    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        try:
            yield TextDelta("partial")
            self.started.set()
            await asyncio.Event().wait()
        finally:
            self.stream_closed = True


async def test_conversation_retains_successful_multi_turn_context() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)

    first = "".join(
        [chunk async for chunk in conversation.send("First question", model="susanoox-fast")]
    )
    second = "".join(
        [chunk async for chunk in conversation.send("Follow-up", model="susanoox-fast")]
    )

    assert first == "Hello world"
    assert second == "Hello world"
    assert client.models == ["susanoox-fast", "susanoox-fast"]
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
        async for _chunk in conversation.send("Cancelled prompt", model="susanoox-fast"):
            pass

    task = asyncio.create_task(consume())
    await client.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(conversation.messages) == 1
    assert client.stream_closed
    assert conversation.unaccounted_requests == 1


async def test_empty_response_is_retryable_and_not_committed() -> None:
    conversation = ConversationService(FakeChatClient(response=(" ", "\n")))

    with pytest.raises(ServiceResponseError, match="retry"):
        _ = [part async for part in conversation.send("Prompt", model="susanoox-fast")]

    assert len(conversation.messages) == 1


async def test_conversation_tracks_exact_usage_by_model() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)

    _ = [part async for part in conversation.send("Fast", model="susanoox-fast")]
    _ = [part async for part in conversation.send("Large", model="susanoox-large")]

    assert conversation.usage.prompt_tokens == 6
    assert conversation.usage.completion_tokens == 4
    assert conversation.usage.total_tokens == 10
    assert dict(conversation.usage_by_model)["susanoox-fast"].total_tokens == 5
    assert dict(conversation.usage_by_model)["susanoox-large"].total_tokens == 5
    assert conversation.unaccounted_requests == 0


async def test_mixed_usage_metadata_remains_partial_after_clear() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)
    _ = [part async for part in conversation.send("Known", model="susanoox-fast")]
    client.usage = None
    _ = [part async for part in conversation.send("Unknown", model="susanoox-fast")]
    conversation.clear()
    assert conversation.usage.total_tokens == 5
    assert conversation.unaccounted_requests == 1


async def test_image_is_committed_to_successful_conversation_context() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)
    attachment = ImageAttachment(
        filename="screen.png",
        media_type="image/png",
        data=b"image-bytes",
    )

    result = "".join(
        [
            part
            async for part in conversation.send(
                "What is shown?",
                model="susanoox-fast",
                images=(attachment,),
            )
        ]
    )

    assert result == "Hello world"
    assert conversation.messages[-2].images == (attachment,)


async def test_old_image_payloads_are_pruned_from_long_conversations() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)
    image_data = b"x" * (MAX_CONTEXT_IMAGE_BYTES // 2)
    attachment = ImageAttachment(
        filename="screen.png",
        media_type="image/png",
        data=image_data,
    )

    for index in range(3):
        _ = [
            part
            async for part in conversation.send(
                f"Image {index}",
                model="susanoox-fast",
                images=(attachment,),
            )
        ]

    user_messages = [message for message in conversation.messages if message.role == "user"]
    assert user_messages[0].images == ()
    assert user_messages[1].images == (attachment,)
    assert user_messages[2].images == (attachment,)
