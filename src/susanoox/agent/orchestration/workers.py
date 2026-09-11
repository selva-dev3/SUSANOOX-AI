from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.capabilities import BoundCapabilities
from susanoox.agent.orchestration.models import AgentRole, ResourceClaim, TaskResult
from susanoox.agent.orchestration.routing import TaskComplexity
from susanoox.agent.types import AgentTask, TaskKind
from susanoox.config.settings import ModelName
from susanoox.permissions.policy import PermissionCategory


class SubAgentContext(BaseModel):
    """Explicit minimal context contract for one delegated task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str = Field(min_length=1, max_length=2_000)
    acceptance_criteria: tuple[str, ...] = ()
    context_items: tuple[str, ...] = ()
    dependency_summaries: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    workspace_revision: str | None = Field(default=None, max_length=128)
    model: ModelName = "susanoox-fast"


TaskOperation = Callable[
    [AgentTask, SubAgentContext, BoundCapabilities, CancellationToken], Awaitable[TaskResult]
]
ClaimResolver = Callable[[AgentTask], tuple[ResourceClaim, ...]]


def no_claims(_task: AgentTask) -> tuple[ResourceClaim, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class WorkerDefinition:
    kind: TaskKind
    role: AgentRole
    operation: TaskOperation
    allowed_tools: tuple[str, ...] = ()
    allowed_permissions: tuple[PermissionCategory, ...] = ()
    claims: ClaimResolver = no_claims
    complexity: TaskComplexity = TaskComplexity.LIGHT


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[TaskKind, WorkerDefinition] = {}

    def register(self, worker: WorkerDefinition) -> None:
        if worker.kind in self._workers:
            raise ValueError(f"A worker is already registered for {worker.kind}.")
        self._workers[worker.kind] = worker

    def get(self, kind: TaskKind) -> WorkerDefinition | None:
        return self._workers.get(kind)
