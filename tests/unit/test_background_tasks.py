from __future__ import annotations

import asyncio
import time

import pytest

from susanoox.agent.orchestration.background import BackgroundContext, BackgroundTaskManager
from susanoox.agent.orchestration.models import BackgroundStatus, BackgroundTask


class SlowStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[BackgroundStatus] = []

    def save_background_task(self, task: BackgroundTask) -> None:
        time.sleep(0.05)
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.saved.append(task.status)


@pytest.mark.asyncio
async def test_background_task_completes_and_retains_summary() -> None:
    async def operation(_context: BackgroundContext) -> str:
        await asyncio.sleep(0)
        return "12 tests passed"

    manager = BackgroundTaskManager()
    task = manager.start("Tests", operation)

    result = await manager.wait(task.id)

    assert result.status is BackgroundStatus.COMPLETED
    assert result.result_summary == "12 tests passed"


@pytest.mark.asyncio
async def test_background_task_can_be_cancelled_without_orphaning_worker() -> None:
    started = asyncio.Event()

    async def operation(context: BackgroundContext) -> None:
        started.set()
        while True:
            await asyncio.sleep(0.01)
            await context.checkpoint()

    manager = BackgroundTaskManager()
    task = manager.start("Index", operation, checkpointable=True)
    await started.wait()

    assert manager.cancel(task.id)
    result = await manager.wait(task.id)

    assert result.status is BackgroundStatus.CANCELLED
    assert not manager.cancel(task.id)


@pytest.mark.asyncio
async def test_non_checkpointable_task_cannot_be_paused() -> None:
    gate = asyncio.Event()

    async def operation(_context: BackgroundContext) -> None:
        await gate.wait()

    manager = BackgroundTaskManager()
    task = manager.start("Build", operation)
    await asyncio.sleep(0)
    assert not manager.pause(task.id)
    manager.cancel(task.id)
    await manager.wait(task.id)


@pytest.mark.asyncio
async def test_checkpointable_task_pauses_and_resumes() -> None:
    started = asyncio.Event()
    checkpoints = 0

    async def operation(context: BackgroundContext) -> str:
        nonlocal checkpoints
        started.set()
        while checkpoints < 2:
            await context.checkpoint()
            checkpoints += 1
            await asyncio.sleep(0.01)
        return "complete"

    manager = BackgroundTaskManager()
    task = manager.start("Index", operation, checkpointable=True)
    await started.wait()
    assert manager.pause(task.id)
    assert manager.tasks[0].status is BackgroundStatus.PAUSED
    assert manager.resume(task.id)

    result = await manager.wait(task.id)
    assert result.status is BackgroundStatus.COMPLETED


@pytest.mark.asyncio
async def test_slow_persistence_does_not_block_start_or_lose_order() -> None:
    store = SlowStore()

    async def operation(_context: BackgroundContext) -> str:
        return "done"

    manager = BackgroundTaskManager(store=store)
    started_at = time.monotonic()
    task = manager.start("Tests", operation)
    start_duration = time.monotonic() - started_at

    result = await manager.wait(task.id)

    assert start_duration < 0.03
    assert result.status is BackgroundStatus.COMPLETED
    assert store.saved == [
        BackgroundStatus.QUEUED,
        BackgroundStatus.RUNNING,
        BackgroundStatus.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_persistence_failure_does_not_change_operation_result() -> None:
    async def operation(_context: BackgroundContext) -> str:
        return "done"

    manager = BackgroundTaskManager(store=SlowStore(fail=True))
    task = manager.start("Tests", operation)

    result = await manager.wait(task.id)

    assert result.status is BackgroundStatus.COMPLETED
    assert result.result_summary == "done"
