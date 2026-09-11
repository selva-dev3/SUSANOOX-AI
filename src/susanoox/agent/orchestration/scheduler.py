from __future__ import annotations

from collections.abc import Callable, Iterable

from susanoox.agent.orchestration.models import ResourceClaim, ResourceMode
from susanoox.agent.orchestration.workers import WorkerDefinition
from susanoox.agent.types import AgentTask

WorkerLookup = Callable[[AgentTask], WorkerDefinition | None]


class DependencyScheduler:
    """Select a deterministic, resource-compatible bounded task batch."""

    def __init__(self, *, max_parallel_tasks: int = 2) -> None:
        if max_parallel_tasks < 1 or max_parallel_tasks > 8:
            raise ValueError("max_parallel_tasks must be from 1 to 8")
        self.max_parallel_tasks = max_parallel_tasks

    def select(
        self, tasks: Iterable[AgentTask], worker_lookup: WorkerLookup
    ) -> tuple[AgentTask, ...]:
        selected: list[AgentTask] = []
        claims: list[ResourceClaim] = []
        for task in tasks:
            if len(selected) >= self.max_parallel_tasks:
                break
            worker = worker_lookup(task)
            if worker is None:
                selected.append(task)
                continue
            task_claims = worker.claims(task)
            if any(
                self._conflicts(candidate, existing)
                for candidate in task_claims
                for existing in claims
            ):
                continue
            selected.append(task)
            claims.extend(task_claims)
        return tuple(selected)

    @staticmethod
    def _conflicts(left: ResourceClaim, right: ResourceClaim) -> bool:
        same_resource = left.key == right.key or left.key == "workspace" or right.key == "workspace"
        return same_resource and (
            left.mode is ResourceMode.WRITE or right.mode is ResourceMode.WRITE
        )
