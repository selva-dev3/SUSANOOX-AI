from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.models import BackgroundStatus, BackgroundTask
from susanoox.agent.types import utc_now

_LOGGER = logging.getLogger(__name__)


class BackgroundTaskStore(Protocol):
    def save_background_task(self, task: BackgroundTask) -> None: ...


@dataclass(slots=True)
class BackgroundContext:
    cancellation: CancellationToken
    checkpointable: bool
    _resume: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self._resume.set()

    async def checkpoint(self) -> None:
        self.cancellation.checkpoint()
        await self._resume.wait()
        self.cancellation.checkpoint()

    def pause(self) -> bool:
        if not self.checkpointable:
            return False
        self._resume.clear()
        return True

    def resume(self) -> None:
        self._resume.set()


BackgroundOperation = Callable[[BackgroundContext], Awaitable[str | None]]


class BackgroundTaskManager:
    """Own real in-process background jobs with bounded concurrency and cleanup."""

    def __init__(self, *, max_active: int = 2, store: BackgroundTaskStore | None = None) -> None:
        if max_active < 1 or max_active > 4:
            raise ValueError("max_active must be from 1 to 4")
        self._semaphore = asyncio.Semaphore(max_active)
        self._store = store
        self._records: dict[str, BackgroundTask] = {}
        self._contexts: dict[str, BackgroundContext] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._persistence_queue: asyncio.Queue[BackgroundTask] = asyncio.Queue()
        self._persistence_worker: asyncio.Task[None] | None = None

    @property
    def tasks(self) -> tuple[BackgroundTask, ...]:
        return tuple(self._records.values())

    def start(
        self,
        title: str,
        operation: BackgroundOperation,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        checkpointable: bool = False,
        workspace_revision: str | None = None,
    ) -> BackgroundTask:
        record = BackgroundTask(
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            title=title,
            status=BackgroundStatus.QUEUED,
            workspace_revision=workspace_revision,
        )
        context = BackgroundContext(CancellationToken(), checkpointable)
        self._records[record.id] = record
        self._contexts[record.id] = context
        self._save(record)
        worker = asyncio.create_task(self._run(record.id, operation))
        self._workers[record.id] = worker
        worker.add_done_callback(lambda _finished: self._workers.pop(record.id, None))
        return record

    def pause(self, task_id: str) -> bool:
        context = self._contexts.get(task_id)
        record = self._records.get(task_id)
        if context is None or record is None or record.status is not BackgroundStatus.RUNNING:
            return False
        if not context.pause():
            return False
        self._update(record, BackgroundStatus.PAUSED)
        return True

    def resume(self, task_id: str) -> bool:
        context = self._contexts.get(task_id)
        record = self._records.get(task_id)
        if context is None or record is None or record.status is not BackgroundStatus.PAUSED:
            return False
        context.resume()
        self._update(record, BackgroundStatus.RUNNING)
        return True

    def cancel(self, task_id: str) -> bool:
        context = self._contexts.get(task_id)
        worker = self._workers.get(task_id)
        if context is None or worker is None or worker.done():
            return False
        context.cancellation.cancel("Background task cancelled by user")
        context.resume()
        worker.cancel()
        return True

    async def wait(self, task_id: str) -> BackgroundTask:
        worker = self._workers.get(task_id)
        if worker is not None:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        await self._flush_persistence()
        return self._records[task_id]

    async def shutdown(self) -> None:
        for task_id in tuple(self._workers):
            self.cancel(task_id)
        await asyncio.gather(*tuple(self._workers.values()), return_exceptions=True)
        await self._flush_persistence()

    async def _run(self, task_id: str, operation: BackgroundOperation) -> None:
        record = self._records[task_id]
        context = self._contexts[task_id]
        try:
            async with self._semaphore:
                self._update(record, BackgroundStatus.RUNNING)
                result = await operation(context)
                context.cancellation.checkpoint()
            self._update(self._records[task_id], BackgroundStatus.COMPLETED, result_summary=result)
        except asyncio.CancelledError:
            self._update(self._records[task_id], BackgroundStatus.CANCELLED)
            raise
        except Exception:
            self._update(
                self._records[task_id],
                BackgroundStatus.FAILED,
                result_summary="Background task failed.",
            )
        finally:
            self._contexts.pop(task_id, None)

    def _update(
        self,
        record: BackgroundTask,
        status: BackgroundStatus,
        *,
        result_summary: str | None = None,
    ) -> BackgroundTask:
        updated = record.model_copy(
            update={
                "status": status,
                "result_summary": result_summary,
                "updated_at": utc_now(),
            }
        )
        self._records[record.id] = updated
        self._save(updated)
        return updated

    def _save(self, task: BackgroundTask) -> None:
        if self._store is None:
            return
        self._persistence_queue.put_nowait(task)
        if self._persistence_worker is None or self._persistence_worker.done():
            self._persistence_worker = asyncio.create_task(self._drain_persistence())

    async def _drain_persistence(self) -> None:
        if self._store is None:
            return
        while not self._persistence_queue.empty():
            task = self._persistence_queue.get_nowait()
            try:
                await asyncio.to_thread(self._store.save_background_task, task)
            except Exception as error:
                _LOGGER.warning(
                    "Background task state could not be persisted (%s)", type(error).__name__
                )
            finally:
                self._persistence_queue.task_done()

    async def _flush_persistence(self) -> None:
        await self._persistence_queue.join()
        if self._persistence_worker is not None:
            await self._persistence_worker
