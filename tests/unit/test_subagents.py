from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.capabilities import BoundCapabilities
from susanoox.agent.orchestration.models import AgentRole, AgentRun, TaskResult, task_from_plan_step
from susanoox.agent.orchestration.routing import TaskComplexity
from susanoox.agent.orchestration.subagents import SubAgentManager
from susanoox.agent.orchestration.workers import SubAgentContext, WorkerDefinition
from susanoox.agent.types import AgentTask, TaskKind, TaskStatus
from susanoox.permissions.policy import PermissionCategory


@pytest.mark.asyncio
async def test_subagent_receives_only_explicit_context_contract() -> None:
    received: SubAgentContext | None = None

    async def operation(
        _task: AgentTask,
        context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        nonlocal received
        received = context
        return TaskResult(summary="reviewed")

    worker = WorkerDefinition(
        kind=TaskKind.EXPLAIN,
        role=AgentRole.CONTEXT,
        operation=operation,
        allowed_tools=("read_file",),
    )
    run = AgentRun(session_id="session", objective="Explain")
    task = task_from_plan_step(run=run, title="Inspect", kind=TaskKind.EXPLAIN)
    context = SubAgentContext(
        objective=task.objective,
        context_items=("src/auth.py",),
        allowed_tools=worker.allowed_tools,
    )

    agent, result = await SubAgentManager().run(worker, task, context, CancellationToken())

    assert received == context
    assert agent.status is TaskStatus.COMPLETED
    assert result.summary == "reviewed"


@pytest.mark.asyncio
async def test_subagent_concurrency_is_bounded() -> None:
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

    worker = WorkerDefinition(
        kind=TaskKind.CONVERSATION,
        role=AgentRole.CODE,
        operation=operation,
    )
    run = AgentRun(session_id="session", objective="Bound work")
    tasks = tuple(task_from_plan_step(run=run, title=str(index)) for index in range(3))
    manager = SubAgentManager(max_active=1)
    context = SubAgentContext(objective="Bound work")

    await asyncio.gather(
        *(manager.run(worker, task, context, CancellationToken()) for task in tasks)
    )

    assert peak == 1


@pytest.mark.asyncio
async def test_subagent_cannot_exceed_parent_permission_ceiling() -> None:
    async def operation(
        _task: AgentTask,
        _context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        return TaskResult()

    worker = WorkerDefinition(
        kind=TaskKind.EDIT,
        role=AgentRole.CODE,
        operation=operation,
        allowed_permissions=(PermissionCategory.FILE_WRITE,),
    )
    run = AgentRun(session_id="session", objective="Edit")
    task = task_from_plan_step(run=run, title="Edit", kind=TaskKind.EDIT)

    with pytest.raises(PermissionError, match="permission ceiling"):
        await SubAgentManager(parent_permissions=(PermissionCategory.FILE_READ,)).run(
            worker,
            task,
            SubAgentContext(objective="Edit"),
            CancellationToken(),
        )


@pytest.mark.asyncio
async def test_subagent_uses_model_router_for_complex_code_work() -> None:
    selected_model = ""

    async def operation(
        _task: AgentTask,
        context: SubAgentContext,
        _capabilities: BoundCapabilities,
        _token: CancellationToken,
    ) -> TaskResult:
        nonlocal selected_model
        selected_model = context.model
        return TaskResult()

    worker = WorkerDefinition(
        kind=TaskKind.EDIT,
        role=AgentRole.CODE,
        operation=operation,
        complexity=TaskComplexity.COMPLEX,
    )
    run = AgentRun(session_id="session", objective="Edit")
    task = task_from_plan_step(run=run, title="Edit", kind=TaskKind.EDIT)

    agent, _result = await SubAgentManager().run(
        worker, task, SubAgentContext(objective="Edit"), CancellationToken()
    )

    assert agent.config.model == "susanoox-large"
    assert selected_model == "susanoox-large"
