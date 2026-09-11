from __future__ import annotations

import asyncio
from typing import Protocol

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.capabilities import CapabilityExecutor
from susanoox.agent.orchestration.models import SubAgent, SubAgentConfig, TaskResult
from susanoox.agent.orchestration.routing import ModelRouter
from susanoox.agent.orchestration.workers import SubAgentContext, WorkerDefinition
from susanoox.agent.types import AgentTask, TaskStatus, utc_now
from susanoox.permissions.policy import PermissionCategory


class SubAgentStore(Protocol):
    def save_subagent(self, agent: SubAgent) -> None: ...


class SubAgentManager:
    """Run depth-one, capability-bounded workers with isolated task context."""

    def __init__(
        self,
        *,
        max_active: int = 2,
        store: SubAgentStore | None = None,
        parent_permissions: tuple[PermissionCategory, ...] = (),
        capabilities: CapabilityExecutor | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        if max_active < 1 or max_active > 4:
            raise ValueError("max_active must be from 1 to 4")
        self._semaphore = asyncio.Semaphore(max_active)
        self._agents: dict[str, SubAgent] = {}
        self._store = store
        self._parent_permissions = frozenset(parent_permissions)
        self._capabilities = capabilities or CapabilityExecutor()
        self._model_router = model_router or ModelRouter()

    @property
    def agents(self) -> tuple[SubAgent, ...]:
        return tuple(self._agents.values())

    async def run(
        self,
        worker: WorkerDefinition,
        task: AgentTask,
        context: SubAgentContext,
        token: CancellationToken,
    ) -> tuple[SubAgent, TaskResult]:
        if task.run_id is None:
            raise ValueError("A delegated task must belong to a run")
        if not set(worker.allowed_permissions).issubset(self._parent_permissions):
            raise PermissionError("A sub-agent cannot exceed its parent permission ceiling")
        model = self._model_router.select(worker.role, worker.complexity)
        context = context.model_copy(update={"model": model})
        config = SubAgentConfig(
            role=worker.role,
            model=model,
            allowed_tools=worker.allowed_tools,
            allowed_permissions=worker.allowed_permissions,
        )
        agent = SubAgent(run_id=task.run_id, parent_task_id=task.id, config=config)
        self._agents[agent.id] = agent
        await self._save(agent)
        async with self._semaphore:
            token.checkpoint()
            running = agent.model_copy(
                update={"status": TaskStatus.RUNNING, "updated_at": utc_now()}
            )
            self._agents[agent.id] = running
            await self._save(running)
            try:
                capabilities = self._capabilities.bind(
                    allowed_tools=worker.allowed_tools,
                    allowed_permissions=worker.allowed_permissions,
                )
                async with self._model_router.lease(model):
                    result = await worker.operation(task, context, capabilities, token)
                token.checkpoint()
            except asyncio.CancelledError:
                cancelled = running.model_copy(
                    update={"status": TaskStatus.CANCELLED, "updated_at": utc_now()}
                )
                self._agents[agent.id] = cancelled
                await self._save(cancelled)
                raise
            except Exception:
                failed = running.model_copy(
                    update={"status": TaskStatus.FAILED, "updated_at": utc_now()}
                )
                self._agents[agent.id] = failed
                await self._save(failed)
                raise
            completed = running.model_copy(
                update={"status": TaskStatus.COMPLETED, "updated_at": utc_now()}
            )
            self._agents[agent.id] = completed
            await self._save(completed)
            return completed, result

    async def _save(self, agent: SubAgent) -> None:
        if self._store is not None:
            await asyncio.to_thread(self._store.save_subagent, agent)
