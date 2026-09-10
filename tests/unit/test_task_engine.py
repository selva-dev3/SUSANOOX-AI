from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.activity import ActivityPublisher, CancellationToken
from susanoox.agent.task_engine import TaskEngine
from susanoox.agent.types import AgentEvent, AgentTask, TaskKind, TaskStatus


def make_task() -> AgentTask:
    return AgentTask(session_id="session", kind=TaskKind.SEARCH, objective="Find authentication")


async def test_task_engine_publishes_successful_lifecycle() -> None:
    activity = ActivityPublisher()
    engine = TaskEngine(activity=activity)
    task = make_task()

    async def operation(
        running: AgentTask, token: CancellationToken, publisher: ActivityPublisher
    ) -> str:
        assert running.status is TaskStatus.RUNNING
        assert engine.active_task == running
        token.checkpoint()
        publisher.publish(
            AgentEvent(task_id=running.id, kind="searching", message="Searching codebase")
        )
        return "done"

    assert await engine.run(task, operation) == "done"
    assert engine.active_task is None
    assert engine.last_task is not None
    assert engine.last_task.status is TaskStatus.COMPLETED
    assert [event.kind for event in activity.history] == [
        "thinking",
        "searching",
        "completed",
    ]


async def test_task_engine_cancels_cooperative_operation() -> None:
    engine = TaskEngine()
    started = asyncio.Event()

    async def operation(
        _task: AgentTask, token: CancellationToken, _publisher: ActivityPublisher
    ) -> None:
        started.set()
        await token.wait()
        token.checkpoint()

    running = asyncio.create_task(engine.run(make_task(), operation))
    await started.wait()
    assert engine.cancel("Cancelled by test")

    with pytest.raises(asyncio.CancelledError):
        await running
    assert engine.last_task is not None
    assert engine.last_task.status is TaskStatus.CANCELLED
    assert engine.activity.history[-1].kind == "cancelled"
    assert engine.activity.history[-1].message == "Cancelled by test"


async def test_task_engine_records_failure_without_exposing_exception_text() -> None:
    engine = TaskEngine()

    async def operation(
        _task: AgentTask, _token: CancellationToken, _publisher: ActivityPublisher
    ) -> None:
        raise RuntimeError("secret failure detail")

    with pytest.raises(RuntimeError, match="secret failure detail"):
        await engine.run(make_task(), operation)

    assert engine.last_task is not None
    assert engine.last_task.status is TaskStatus.FAILED
    assert engine.activity.history[-1].message == "Task failed"
    assert "secret" not in engine.activity.history[-1].message


async def test_cancelled_activity_subscriber_cannot_wedge_task_engine() -> None:
    activity = ActivityPublisher()

    def cancel(_event: AgentEvent) -> None:
        raise asyncio.CancelledError

    activity.subscribe(cancel)
    engine = TaskEngine(activity=activity)

    async def operation(
        _task: AgentTask, _token: CancellationToken, _publisher: ActivityPublisher
    ) -> str:
        return "done"

    assert await engine.run(make_task(), operation) == "done"
    assert engine.active_task is None
    assert engine.last_task is not None
    assert engine.last_task.status is TaskStatus.COMPLETED

    assert await engine.run(make_task(), operation) == "done"


async def test_task_engine_rejects_concurrent_task() -> None:
    engine = TaskEngine()
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation(
        _task: AgentTask, _token: CancellationToken, _publisher: ActivityPublisher
    ) -> None:
        started.set()
        await release.wait()

    first = asyncio.create_task(engine.run(make_task(), operation))
    await started.wait()
    with pytest.raises(RuntimeError, match="already running"):
        await engine.run(make_task(), operation)
    release.set()
    await first
