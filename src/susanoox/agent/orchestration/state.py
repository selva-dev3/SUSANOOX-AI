from __future__ import annotations

from susanoox.agent.orchestration.models import RunStatus
from susanoox.agent.types import TaskStatus
from susanoox.utils.errors import SusanooxError


class InvalidStateTransition(SusanooxError):
    """A task or run attempted an invalid lifecycle transition."""


_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.QUEUED, TaskStatus.BLOCKED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
    ),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.RETRYING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }
    ),
    TaskStatus.RETRYING: frozenset({TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.BLOCKED: frozenset({TaskStatus.PENDING, TaskStatus.SKIPPED, TaskStatus.CANCELLED}),
    TaskStatus.INTERRUPTED: frozenset(
        {TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}

_RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset(
        {RunStatus.RUNNING, RunStatus.WAITING_APPROVAL, RunStatus.CANCELLED}
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.PENDING, RunStatus.PLANNED, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.PLANNED: frozenset({RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.INTERRUPTED: frozenset({RunStatus.PENDING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in _TASK_TRANSITIONS[current]:
        raise InvalidStateTransition(f"Task cannot transition from {current} to {target}.")


def validate_run_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _RUN_TRANSITIONS[current]:
        raise InvalidStateTransition(f"Run cannot transition from {current} to {target}.")
