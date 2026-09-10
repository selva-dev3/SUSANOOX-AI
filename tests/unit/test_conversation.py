from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest

from susanoox.agent.retry import RetryPolicy
from susanoox.agent.types import AgentEvent
from susanoox.config.settings import ModelName
from susanoox.context.models import ContextFile, ContextSnapshot
from susanoox.conversations.service import MAX_CONTEXT_IMAGE_BYTES, ConversationService
from susanoox.models.protocol import ConversationMessage, ImageAttachment, StreamEvent, TextDelta
from susanoox.summarization.service import ConversationSummarizer
from susanoox.utils.errors import ContextOverflowError, RetryableServiceError, ServiceResponseError
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


class TransientChatClient(FakeChatClient):
    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        if len(self.requests) == 1:
            raise RetryableServiceError("temporary")
        yield TextDelta("recovered")


class EmptyThenValidClient(FakeChatClient):
    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        yield TextDelta(" " if len(self.requests) == 1 else "valid")


class OverflowThenValidClient(FakeChatClient):
    async def stream_chat(
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.requests.append(tuple(messages))
        self.models.append(model)
        if len(self.requests) == 1:
            raise ContextOverflowError("context too large")
        yield TextDelta("recovered with context")


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


async def test_conversation_retries_transient_pre_output_failure() -> None:
    client = TransientChatClient()
    conversation = ConversationService(
        client,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0),
    )

    result = "".join([part async for part in conversation.send("hello", model="susanoox-fast")])

    assert result == "recovered"
    assert len(client.requests) == 2
    assert conversation.completed_requests == 1


async def test_conversation_compacts_old_context_but_retains_raw_messages() -> None:
    client = FakeChatClient(response=("response",))
    conversation = ConversationService(
        client,
        summarizer=ConversationSummarizer(trigger_chars=10, recent_messages=2),
    )

    for index in range(4):
        _ = [
            part
            async for part in conversation.send(
                f"Long prompt {index} about src/auth.py", model="susanoox-fast"
            )
        ]

    assert conversation.summary is not None
    assert len(conversation.messages) == 9
    assert any(
        message.role == "system" and "Conversation summary" in message.content
        for message in client.requests[-1]
    )


async def test_empty_model_output_is_corrected_once_before_exposure() -> None:
    client = EmptyThenValidClient()
    conversation = ConversationService(
        client,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
    )

    result = "".join([part async for part in conversation.send("hello", model="susanoox-fast")])

    assert result.strip() == "valid"
    assert len(client.requests) == 2


async def test_preselected_context_is_transient_and_marked_untrusted() -> None:
    client = FakeChatClient()
    conversation = ConversationService(client)
    snapshot = ContextSnapshot(
        query="fix auth",
        project_root="/project",
        files=(
            ContextFile(
                path="src/auth.py",
                score=10,
                reasons=("path matches",),
                excerpt="def login(): pass",
            ),
        ),
        total_chars=17,
    )

    _ = [
        part
        async for part in conversation.send(
            "fix auth",
            model="susanoox-fast",
            context_snapshot=snapshot,
        )
    ]

    request = client.requests[0]
    assert any("untrusted reference data" in message.content for message in request)
    assert all(
        "untrusted reference data" not in message.content for message in conversation.messages
    )

    _ = [
        part
        async for part in conversation.send(
            "follow up without project context",
            model="susanoox-fast",
        )
    ]

    assert conversation.last_context is None
    assert all("untrusted reference data" not in message.content for message in client.requests[-1])


async def test_context_overflow_retry_retains_reduced_selected_context() -> None:
    client = OverflowThenValidClient()
    conversation = ConversationService(
        client,
        summarizer=ConversationSummarizer(trigger_chars=4_000, recent_messages=2),
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0),
    )
    snapshot = ContextSnapshot(
        query="fix auth",
        project_root="/project",
        files=(
            ContextFile(
                path="src/auth.py",
                score=10,
                reasons=("path matches",),
                excerpt="important implementation\n" * 100,
            ),
        ),
        total_chars=len("important implementation\n" * 100),
    )

    result = "".join(
        [
            part
            async for part in conversation.send(
                "fix auth", model="susanoox-fast", context_snapshot=snapshot
            )
        ]
    )

    assert result == "recovered with context"
    assert len(client.requests) == 2
    retry_context = [
        message.content
        for message in client.requests[1]
        if message.role == "system" and "untrusted reference data" in message.content
    ]
    assert len(retry_context) == 1
    assert "src/auth.py" in retry_context[0]
    assert "important implementation" in retry_context[0]
    assert len(retry_context[0]) < len(
        next(
            message.content
            for message in client.requests[0]
            if message.role == "system" and "untrusted reference data" in message.content
        )
    )


async def test_reauthentication_rebinds_activity_handler_with_client() -> None:
    old_events: list[AgentEvent] = []
    new_events: list[AgentEvent] = []
    original = FakeChatClient()
    replacement = FakeChatClient()
    conversation = ConversationService(original, on_event=old_events.append)
    conversation.replace_client(replacement, on_event=new_events.append)
    snapshot = ContextSnapshot(
        query="auth",
        project_root="/project",
        files=(),
        total_chars=0,
    )

    _ = [
        part
        async for part in conversation.send(
            "hello", model="susanoox-fast", context_snapshot=snapshot
        )
    ]

    assert original.requests == []
    assert len(replacement.requests) == 1
    assert old_events == []
    assert [event.kind for event in new_events] == ["context_ready"]
