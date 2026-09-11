from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from susanoox.agent.orchestration.models import (
    DependencyCondition,
    TaskDependency,
    TaskProgress,
)
from susanoox.agent.types import AgentTask, TaskStatus
from susanoox.utils.errors import SusanooxError


class TaskGraphError(SusanooxError):
    """A task graph is malformed or cyclic."""


_TERMINAL = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
)


class TaskGraph:
    def __init__(
        self,
        tasks: Iterable[AgentTask],
        dependencies: Iterable[TaskDependency] = (),
        *,
        max_tasks: int = 100,
    ) -> None:
        task_items = tuple(tasks)
        if not task_items:
            raise TaskGraphError("A task graph needs at least one task.")
        if len(task_items) > max_tasks:
            raise TaskGraphError(f"A task graph cannot contain more than {max_tasks} tasks.")
        self.tasks = {task.id: task for task in task_items}
        if len(self.tasks) != len(task_items):
            raise TaskGraphError("Task IDs must be unique within a run.")
        run_ids = {task.run_id for task in task_items}
        if None in run_ids or len(run_ids) != 1:
            raise TaskGraphError("Every task must belong to the same run.")
        self.run_id = next(iter(run_ids))
        dependency_items = tuple(dependencies)
        edge_keys = {(edge.predecessor_id, edge.successor_id) for edge in dependency_items}
        if len(edge_keys) != len(dependency_items):
            raise TaskGraphError("Task dependencies must be unique.")
        for edge in dependency_items:
            if edge.predecessor_id == edge.successor_id:
                raise TaskGraphError("A task cannot depend on itself.")
            if edge.predecessor_id not in self.tasks or edge.successor_id not in self.tasks:
                raise TaskGraphError("Task dependency references an unknown task.")
        self.dependencies = dependency_items
        self._validate_hierarchy()
        self._predecessors: dict[str, list[TaskDependency]] = defaultdict(list)
        self._successors: dict[str, list[str]] = defaultdict(list)
        for edge in dependency_items:
            self._predecessors[edge.successor_id].append(edge)
            self._successors[edge.predecessor_id].append(edge.successor_id)
        self._validate_acyclic()

    def _validate_hierarchy(self) -> None:
        child_counts: dict[str, int] = defaultdict(int)
        for task in self.tasks.values():
            if task.parent_task_id is None:
                continue
            if task.parent_task_id == task.id:
                raise TaskGraphError("A task cannot be its own parent.")
            if task.parent_task_id not in self.tasks:
                raise TaskGraphError("A parent task must belong to the same graph.")
            child_counts[task.parent_task_id] += 1
            parent = self.tasks[task.parent_task_id]
            if child_counts[task.parent_task_id] > parent.budget.max_children:
                raise TaskGraphError("A task exceeds its bounded child-task budget.")
            visited = {task.id}
            current = task
            while current.parent_task_id is not None:
                if current.parent_task_id in visited:
                    raise TaskGraphError("Task parent relationships contain a cycle.")
                visited.add(current.parent_task_id)
                current = self.tasks[current.parent_task_id]

    def _validate_acyclic(self) -> None:
        indegree = {task_id: len(self._predecessors[task_id]) for task_id in self.tasks}
        ready = deque(sorted(task_id for task_id, count in indegree.items() if count == 0))
        visited = 0
        while ready:
            task_id = ready.popleft()
            visited += 1
            for successor in sorted(self._successors[task_id]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        if visited != len(self.tasks):
            raise TaskGraphError("Task dependencies contain a cycle.")

    def replace(self, task: AgentTask) -> None:
        if task.id not in self.tasks or task.run_id != self.run_id:
            raise TaskGraphError("Updated task does not belong to this graph.")
        self.tasks[task.id] = task

    def ready(self) -> tuple[AgentTask, ...]:
        ready: list[AgentTask] = []
        for task in self.tasks.values():
            if task.status is not TaskStatus.PENDING:
                continue
            dependencies = self._predecessors[task.id]
            if all(self._dependency_satisfied(edge) for edge in dependencies):
                ready.append(task)
        return tuple(sorted(ready, key=lambda item: (-item.priority, item.created_at, item.id)))

    def blocked_by_failure(self) -> tuple[AgentTask, ...]:
        blocked: list[AgentTask] = []
        for task in self.tasks.values():
            if task.status is not TaskStatus.PENDING:
                continue
            if any(
                edge.condition is DependencyCondition.REQUIRES_SUCCESS
                and self.tasks[edge.predecessor_id].status
                in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
                for edge in self._predecessors[task.id]
            ):
                blocked.append(task)
        return tuple(blocked)

    def _dependency_satisfied(self, edge: TaskDependency) -> bool:
        status = self.tasks[edge.predecessor_id].status
        if edge.condition is DependencyCondition.REQUIRES_SUCCESS:
            return status is TaskStatus.COMPLETED
        return status in _TERMINAL

    def progress(self) -> TaskProgress:
        statuses = tuple(task.status for task in self.tasks.values())
        return TaskProgress(
            total=len(statuses),
            succeeded=statuses.count(TaskStatus.COMPLETED),
            terminal=sum(status in _TERMINAL for status in statuses),
            running=sum(
                status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRYING}
                for status in statuses
            ),
            blocked=statuses.count(TaskStatus.BLOCKED),
        )

    @property
    def terminal(self) -> bool:
        return all(task.status in _TERMINAL for task in self.tasks.values())
