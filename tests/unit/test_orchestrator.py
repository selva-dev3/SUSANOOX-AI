from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.capabilities import BoundCapabilities
from susanoox.agent.orchestration.models import (
    AgentRole,
    AgentRun,
    ResourceClaim,
    ResourceMode,
    RunStatus,
    TaskDependency,
    TaskResult,
    task_from_plan_step,
)
from susanoox.agent.orchestration.orchestrator import AgentOrchestrator
from susanoox.agent.orchestration.recovery import RetryableTaskError
from susanoox.agent.orchestration.workers import (
    ClaimResolver,
    SubAgentContext,
    TaskOperation,
    WorkerDefinition,
    WorkerRegistry,
    no_claims,
)
from susanoox.agent.types import AgentTask, TaskKind, TaskStatus


def _worker(operation: TaskOperation, *, claims: ClaimResolver = no_claims) -> WorkerDefinition:
    return WorkerDefinition(
        kind=TaskKind.CONVERSATION,
        role=AgentRole.CODE,
        operation=operation,
        claims=claims,
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_independent_tasks_in_parallel() -> None:
    active = 0
    peak = 0

    async def operation(
        _task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return TaskResult(summary="done")

    registry = WorkerRegistry()
    registry.register(_worker(operation))
    orchestrator = AgentOrchestrator(workers=registry, max_parallel_tasks=2, max_subagents=2)
    run = AgentRun(session_id="session", objective="Parallel task")
    tasks = tuple(task_from_plan_step(run=run, title=f"Task {index}") for index in range(2))
    graph = orchestrator.register(run, tasks)

    completed = await orchestrator.execute(run.id)

    assert completed.status is RunStatus.COMPLETED
    assert peak == 2
    assert all(task.status is TaskStatus.COMPLETED for task in graph.tasks.values())


@pytest.mark.asyncio
async def test_write_claims_are_serialized() -> None:
    active = 0
    peak = 0

    async def operation(
        _task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return TaskResult()

    registry = WorkerRegistry()
    registry.register(
        _worker(
            operation,
            claims=lambda _task: (ResourceClaim(key="auth.py", mode=ResourceMode.WRITE),),
        )
    )
    orchestrator = AgentOrchestrator(workers=registry, max_parallel_tasks=2)
    run = AgentRun(session_id="session", objective="Serialized task")
    tasks = tuple(task_from_plan_step(run=run, title=f"Task {index}") for index in range(2))
    orchestrator.register(run, tasks)

    assert (await orchestrator.execute(run.id)).status is RunStatus.COMPLETED
    assert peak == 1


@pytest.mark.asyncio
async def test_retry_is_bounded_and_records_no_progress() -> None:
    attempts = 0

    async def operation(
        _task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        nonlocal attempts
        attempts += 1
        raise RetryableTaskError("temporary")

    registry = WorkerRegistry()
    registry.register(_worker(operation))
    orchestrator = AgentOrchestrator(workers=registry)
    orchestrator.recovery.base_delay_seconds = 0
    run = AgentRun(session_id="session", objective="Retry task")
    task = task_from_plan_step(run=run, title="Fail repeatedly")
    graph = orchestrator.register(run, (task,))

    assert (await orchestrator.execute(run.id)).status is RunStatus.FAILED
    assert attempts == 2
    assert graph.tasks[task.id].status is TaskStatus.FAILED


@pytest.mark.asyncio
async def test_failed_dependency_is_blocked_without_execution() -> None:
    calls: list[str] = []

    async def operation(
        task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        calls.append(task.objective)
        if task.objective == "first":
            raise ValueError("fatal")
        return TaskResult()

    registry = WorkerRegistry()
    registry.register(_worker(operation))
    orchestrator = AgentOrchestrator(workers=registry)
    run = AgentRun(session_id="session", objective="Dependency task")
    first = task_from_plan_step(run=run, title="first")
    second = task_from_plan_step(run=run, title="second")
    graph = orchestrator.register(
        run,
        (first, second),
        (TaskDependency(predecessor_id=first.id, successor_id=second.id),),
    )

    assert (await orchestrator.execute(run.id)).status is RunStatus.FAILED
    assert calls == ["first"]
    assert graph.tasks[second.id].status is TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_interrupted_run_requires_confirmation_and_matching_workspace() -> None:
    orchestrator = AgentOrchestrator()
    run = AgentRun(
        session_id="session",
        objective="Resume task",
        status=RunStatus.INTERRUPTED,
        workspace_revision="before",
    )
    task = task_from_plan_step(run=run, title="Interrupted").model_copy(
        update={"status": TaskStatus.INTERRUPTED}
    )
    graph = orchestrator.register(run, (task,))

    with pytest.raises(ValueError, match="explicit confirmation"):
        await orchestrator.prepare_resume(run.id, confirmed=False)
    with pytest.raises(ValueError, match="workspace changed"):
        await orchestrator.prepare_resume(run.id, confirmed=True, workspace_revision="after")

    resumed = await orchestrator.prepare_resume(run.id, confirmed=True, workspace_revision="before")
    assert resumed.status is RunStatus.PENDING
    assert graph.tasks[task.id].status is TaskStatus.PENDING


@pytest.mark.asyncio
async def test_run_cancellation_propagates_to_active_workers() -> None:
    started = asyncio.Event()

    async def operation(
        _task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        started.set()
        await asyncio.Event().wait()
        return TaskResult()

    registry = WorkerRegistry()
    registry.register(_worker(operation))
    orchestrator = AgentOrchestrator(workers=registry)
    run = AgentRun(session_id="session", objective="Cancel task")
    task = task_from_plan_step(run=run, title="Long operation")
    graph = orchestrator.register(run, (task,))
    execution = asyncio.create_task(orchestrator.execute(run.id))
    await started.wait()

    assert orchestrator.cancel(run.id)
    cancelled = await execution

    assert cancelled.status is RunStatus.CANCELLED
    assert graph.tasks[task.id].status is TaskStatus.CANCELLED
