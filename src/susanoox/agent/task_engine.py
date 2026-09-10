from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from susanoox.agent.activity import ActivityPublisher, CancellationToken
from susanoox.agent.types import ActivityStatus, AgentEvent, AgentTask, TaskStatus, utc_now

_ResultT = TypeVar("_ResultT")
TaskOperation = Callable[[AgentTask, CancellationToken, ActivityPublisher], Awaitable[_ResultT]]


class TaskEngine:
    """Own one bounded task lifecycle; concrete coding workflows are added separately."""

    def __init__(self, *, activity: ActivityPublisher | None = None) -> None:
        self.activity = activity or ActivityPublisher()
        self._active_task: AgentTask | None = None
        self._last_task: AgentTask | None = None
        self._cancellation: CancellationToken | None = None

    @property
    def active_task(self) -> AgentTask | None:
        return self._active_task

    @property
    def last_task(self) -> AgentTask | None:
        return self._last_task

    def cancel(self, reason: str = "Operation cancelled by user") -> bool:
        if self._cancellation is None:
            return False
        self._cancellation.cancel(reason)
        return True

    async def run(self, task: AgentTask, operation: TaskOperation[_ResultT]) -> _ResultT:
        if self._active_task is not None:
            raise RuntimeError("Another task is already running")
        if task.status is not TaskStatus.PENDING:
            raise ValueError("Only pending tasks can be started")

        token = CancellationToken()
        running = task.model_copy(update={"status": TaskStatus.RUNNING, "updated_at": utc_now()})
        self._active_task = running
        self._cancellation = token
        self.activity.publish(
            AgentEvent(
                task_id=task.id,
                kind="thinking",
                status=ActivityStatus.ACTIVE,
                message="Understanding task",
            )
        )
        try:
            async with asyncio.timeout(task.budget.timeout_seconds):
                result = await operation(running, token, self.activity)
            token.checkpoint()
        except asyncio.CancelledError:
            self._last_task = running.model_copy(
                update={"status": TaskStatus.CANCELLED, "updated_at": utc_now()}
            )
            self.activity.publish(
                AgentEvent(
                    task_id=task.id,
                    kind="cancelled",
                    status=ActivityStatus.CANCELLED,
                    message=token.reason,
                )
            )
            raise
        except Exception:
            self._last_task = running.model_copy(
                update={"status": TaskStatus.FAILED, "updated_at": utc_now()}
            )
            self.activity.publish(
                AgentEvent(
                    task_id=task.id,
                    kind="failed",
                    status=ActivityStatus.FAILED,
                    message="Task failed",
                )
            )
            raise
        else:
            self._last_task = running.model_copy(
                update={"status": TaskStatus.COMPLETED, "updated_at": utc_now()}
            )
            self.activity.publish(
                AgentEvent(
                    task_id=task.id,
                    kind="completed",
                    status=ActivityStatus.COMPLETED,
                    message="Task completed",
                )
            )
            return result
        finally:
            self._active_task = None
            self._cancellation = None
