from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.activity import ActivityPublisher, CancellationToken
from susanoox.agent.types import AgentEvent


def test_activity_publisher_bounds_history_and_supports_unsubscribe() -> None:
    publisher = ActivityPublisher(history_limit=2)
    observed: list[str] = []
    unsubscribe = publisher.subscribe(lambda event: observed.append(event.message))

    publisher.publish(AgentEvent(kind="thinking", message="one"))
    publisher.publish(AgentEvent(kind="searching", message="two"))
    unsubscribe()
    publisher.publish(AgentEvent(kind="completed", message="three"))

    assert observed == ["one", "two"]
    assert [event.message for event in publisher.history] == ["two", "three"]


def test_failed_activity_subscriber_does_not_break_other_subscribers() -> None:
    publisher = ActivityPublisher()
    observed: list[str] = []

    def fail(_event: AgentEvent) -> None:
        raise RuntimeError("renderer failed")

    publisher.subscribe(fail)
    publisher.subscribe(lambda event: observed.append(event.message))

    publisher.publish(AgentEvent(kind="thinking", message="still delivered"))

    assert observed == ["still delivered"]


def test_cancelled_activity_subscriber_does_not_escape_or_block_delivery() -> None:
    publisher = ActivityPublisher()
    observed: list[str] = []

    def cancel(_event: AgentEvent) -> None:
        raise asyncio.CancelledError

    publisher.subscribe(cancel)
    publisher.subscribe(lambda event: observed.append(event.message))

    publisher.publish(AgentEvent(kind="thinking", message="still delivered"))

    assert observed == ["still delivered"]


def test_activity_history_limit_is_validated() -> None:
    with pytest.raises(ValueError, match="history_limit"):
        ActivityPublisher(history_limit=0)


async def test_cancellation_token_is_idempotent_and_checkable() -> None:
    token = CancellationToken()
    token.cancel("  stopped   by user  ")
    token.cancel("replacement must be ignored")

    await token.wait()
    assert token.reason == "stopped by user"
    with pytest.raises(asyncio.CancelledError, match="stopped by user"):
        token.checkpoint()
