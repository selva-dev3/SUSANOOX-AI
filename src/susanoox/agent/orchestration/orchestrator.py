from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Iterable

from susanoox.agent.activity import CancellationToken
from susanoox.agent.orchestration.capabilities import CapabilityExecutor
from susanoox.agent.orchestration.events import OrchestrationEventBus
from susanoox.agent.orchestration.graph import TaskGraph
from susanoox.agent.orchestration.models import (
    AgentRun,
    ProgressEvent,
    RecoveryEvent,
    RunStatus,
    TaskAttempt,
    TaskDependency,
)
from susanoox.agent.orchestration.recovery import RecoveryPolicy
from susanoox.agent.orchestration.scheduler import DependencyScheduler
from susanoox.agent.orchestration.state import validate_run_transition, validate_task_transition
from susanoox.agent.orchestration.subagents import SubAgentManager
from susanoox.agent.orchestration.workers import SubAgentContext, WorkerRegistry
from susanoox.agent.types import AgentTask, TaskStatus, utc_now
from susanoox.permissions.policy import PermissionCategory
from susanoox.sessions.orchestration_storage import OrchestrationStore


class AgentOrchestrator:
    """Coordinate bounded task graphs without granting tool authority to workers."""

    def __init__(
        self,
        *,
        workers: WorkerRegistry | None = None,
        events: OrchestrationEventBus | None = None,
        store: OrchestrationStore | None = None,
        max_parallel_tasks: int = 2,
        max_subagents: int = 2,
        allowed_permissions: tuple[PermissionCategory, ...] = (),
        capabilities: CapabilityExecutor | None = None,
    ) -> None:
        self.workers = workers or WorkerRegistry()
        self.events = events or OrchestrationEventBus()
        self.store = store
        self.scheduler = DependencyScheduler(max_parallel_tasks=max_parallel_tasks)
        self.subagents = SubAgentManager(
            max_active=max_subagents,
            store=store,
            parent_permissions=allowed_permissions,
            capabilities=capabilities,
        )
        self.recovery = RecoveryPolicy()
        self._runs: dict[str, tuple[AgentRun, TaskGraph]] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._active: dict[str, dict[str, asyncio.Task[None]]] = {}
        self._sequences: Counter[str] = Counter()
        self._failure_counts: Counter[str] = Counter()

    def register(
        self,
        run: AgentRun,
        tasks: Iterable[AgentTask],
        dependencies: Iterable[TaskDependency] = (),
    ) -> TaskGraph:
        graph = TaskGraph(tasks, dependencies)
        if graph.run_id != run.id:
            raise ValueError("The task graph does not belong to the supplied run")
        self._runs[run.id] = (run, graph)
        if self.store is not None:
            self.store.save_graph(run, graph)
        return graph

    def get(self, run_id: str) -> tuple[AgentRun, TaskGraph] | None:
        current = self._runs.get(run_id)
        if current is not None:
            return current
        if self.store is None:
            return None
        loaded = self.store.load_run(run_id)
        if loaded is not None:
            self._runs[run_id] = loaded
        return loaded

    def adopt(self, run: AgentRun, graph: TaskGraph) -> None:
        """Refresh already-persisted state without inserting a duplicate graph."""
        if graph.run_id != run.id:
            raise ValueError("The task graph does not belong to the supplied run")
        self._runs[run.id] = (run, graph)

    def cancel(self, run_id: str, reason: str = "Operation cancelled by user") -> bool:
        token = self._tokens.get(run_id)
        if token is None:
            return False
        token.cancel(reason)
        for active in tuple(self._active.get(run_id, {}).values()):
            active.cancel()
        return True

    async def cancel_task(self, run_id: str, task_id: str) -> bool:
        loaded = self.get(run_id)
        if loaded is None or task_id not in loaded[1].tasks:
            return False
        active = self._active.get(run_id, {}).get(task_id)
        if active is not None:
            active.cancel()
            return True
        task = loaded[1].tasks[task_id]
        if task.status not in {TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.BLOCKED}:
            return False
        await self._cancel_task(loaded[1], task)
        return True

    async def prepare_resume(
        self,
        run_id: str,
        *,
        confirmed: bool,
        workspace_revision: str | None = None,
    ) -> AgentRun:
        loaded = self.get(run_id)
        if loaded is None:
            raise ValueError("Agent run was not found")
        run, graph = loaded
        if not confirmed:
            raise ValueError("Interrupted work requires explicit confirmation before resuming")
        if run.status is not RunStatus.INTERRUPTED:
            raise ValueError("Only interrupted runs can be prepared for resume")
        if (
            run.workspace_revision is not None
            and workspace_revision is not None
            and run.workspace_revision != workspace_revision
        ):
            raise ValueError("The workspace changed after this run was interrupted")
        for task in tuple(graph.tasks.values()):
            if task.status is TaskStatus.INTERRUPTED:
                await self._set_task(graph, task, TaskStatus.PENDING, "Task ready to resume")
        return await self._set_run(run, RunStatus.PENDING, "Run ready to resume")

    async def execute(self, run_id: str) -> AgentRun:
        loaded = self.get(run_id)
        if loaded is None:
            raise ValueError("Agent run was not found")
        run, graph = loaded
        validate_run_transition(run.status, RunStatus.RUNNING)
        run = await self._set_run(run, RunStatus.RUNNING, "Run started")
        token = CancellationToken()
        self._tokens[run.id] = token
        self._active[run.id] = {}
        iterations = 0
        try:
            async with asyncio.timeout(run.budget.timeout_seconds):
                while not graph.terminal:
                    token.checkpoint()
                    if iterations >= run.budget.max_iterations:
                        for task in tuple(graph.tasks.values()):
                            if task.status is TaskStatus.PENDING:
                                await self._set_task(
                                    graph,
                                    task,
                                    TaskStatus.SKIPPED,
                                    "Task skipped because the run budget was exhausted",
                                )
                        break
                    for task in graph.blocked_by_failure():
                        await self._set_task(graph, task, TaskStatus.BLOCKED, "Task blocked")
                    ready = graph.ready()
                    if not ready:
                        break
                    iterations += 1
                    batch = self.scheduler.select(ready, lambda task: self.workers.get(task.kind))
                    batch = batch[: run.budget.max_parallelism]
                    async with asyncio.TaskGroup() as group:
                        for task in batch:
                            active = group.create_task(self._execute_task(run, graph, task, token))
                            self._active[run.id][task.id] = active
                            active.add_done_callback(
                                lambda _finished, task_id=task.id: self._active.get(run.id, {}).pop(
                                    task_id, None
                                )
                            )
        except asyncio.CancelledError:
            for task in tuple(graph.tasks.values()):
                if task.status in {
                    TaskStatus.PENDING,
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                    TaskStatus.RETRYING,
                    TaskStatus.BLOCKED,
                }:
                    await self._cancel_task(graph, task)
            run = await self._set_run(run, RunStatus.CANCELLED, token.reason)
            return run
        except TimeoutError:
            run = await self._set_run(run, RunStatus.FAILED, "Run timed out")
            return run
        finally:
            self._tokens.pop(run.id, None)
            self._active.pop(run.id, None)

        if token.is_cancelled:
            for task in tuple(graph.tasks.values()):
                await self._cancel_task(graph, task)
            return await self._set_run(run, RunStatus.CANCELLED, token.reason)

        failed = any(
            task.status
            in {
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.CANCELLED,
                TaskStatus.SKIPPED,
            }
            for task in graph.tasks.values()
        )
        target = RunStatus.FAILED if failed or not graph.terminal else RunStatus.COMPLETED
        message = "Run failed" if target is RunStatus.FAILED else "Run completed"
        return await self._set_run(run, target, message)

    async def _execute_task(
        self,
        run: AgentRun,
        graph: TaskGraph,
        task: AgentTask,
        token: CancellationToken,
    ) -> None:
        worker = self.workers.get(task.kind)
        if worker is None:
            queued = await self._set_task(graph, task, TaskStatus.QUEUED, "Task queued")
            running = await self._set_task(graph, queued, TaskStatus.RUNNING, "Task started")
            await self._set_task(
                graph,
                running,
                TaskStatus.FAILED,
                "No worker is registered for this task",
                error="No registered worker can execute this task.",
            )
            return

        current = await self._set_task(graph, task, TaskStatus.QUEUED, "Task queued")
        attempts = 0
        while True:
            token.checkpoint()
            attempts += 1
            current = await self._set_task(
                graph,
                current,
                TaskStatus.RUNNING,
                "Task started",
                attempt_count=attempts,
            )
            started_at = utc_now()
            try:
                context = self._context_for(graph, current, worker.allowed_tools)
                async with asyncio.timeout(current.budget.timeout_seconds):
                    agent, result = await self.subagents.run(worker, current, context, token)
                current = current.model_copy(update={"assigned_agent_id": agent.id})
                attempt = TaskAttempt(
                    task_id=current.id,
                    ordinal=attempts,
                    status=TaskStatus.COMPLETED,
                    started_at=started_at,
                    completed_at=utc_now(),
                )
                if self.store is not None:
                    await asyncio.to_thread(self.store.add_attempt, attempt)
                await self._set_task(
                    graph,
                    current,
                    TaskStatus.COMPLETED,
                    "Task completed",
                    result=result.summary,
                )
                return
            except asyncio.CancelledError:
                await self._cancel_task(graph, current)
                return
            except Exception as error:
                decision = self.recovery.classify(error)
                fingerprint = self.recovery.fingerprint(
                    current.id,
                    decision.category,
                    "\0".join((current.workspace_revision or "", decision.safe_message)),
                )
                self._failure_counts[fingerprint] += 1
                retryable = (
                    decision.retryable
                    and attempts <= current.budget.max_retries
                    and self._failure_counts[fingerprint] < 2
                )
                attempt = TaskAttempt(
                    task_id=current.id,
                    ordinal=attempts,
                    status=TaskStatus.RETRYING if retryable else TaskStatus.FAILED,
                    error_fingerprint=fingerprint,
                    started_at=started_at,
                    completed_at=utc_now(),
                )
                if self.store is not None:
                    await asyncio.to_thread(self.store.add_attempt, attempt)
                if not retryable:
                    await self._set_task(
                        graph,
                        current,
                        TaskStatus.FAILED,
                        "Task failed",
                        error=decision.safe_message,
                    )
                    return
                if self.store is not None:
                    recovery_event = RecoveryEvent(
                        run_id=run.id,
                        task_id=current.id,
                        category=decision.category,
                        action="Retry task after a recoverable failure",
                        attempt=attempts,
                        outcome=decision.safe_message,
                    )
                    await asyncio.to_thread(self.store.add_recovery_event, recovery_event)
                current = await self._set_task(
                    graph,
                    current,
                    TaskStatus.RETRYING,
                    f"Recovery attempt {attempts} / {current.budget.max_retries}",
                    error=decision.safe_message,
                )
                await asyncio.sleep(self.recovery.delay(attempts))
                current = await self._set_task(
                    graph, current, TaskStatus.QUEUED, "Task queued for retry"
                )

    @staticmethod
    def _context_for(
        graph: TaskGraph, task: AgentTask, allowed_tools: tuple[str, ...]
    ) -> SubAgentContext:
        dependencies = [
            graph.tasks[edge.predecessor_id]
            for edge in graph.dependencies
            if edge.successor_id == task.id
        ]
        summaries = tuple(
            dependency.result_summary
            for dependency in dependencies
            if dependency.result_summary is not None
        )
        return SubAgentContext(
            objective=task.objective,
            dependency_summaries=summaries,
            allowed_tools=allowed_tools,
            workspace_revision=task.workspace_revision,
        )

    async def _set_task(
        self,
        graph: TaskGraph,
        task: AgentTask,
        status: TaskStatus,
        message: str,
        *,
        result: str | None = None,
        error: str | None = None,
        attempt_count: int | None = None,
    ) -> AgentTask:
        validate_task_transition(task.status, status)
        updates: dict[str, object] = {"status": status, "updated_at": utc_now()}
        if result is not None:
            updates["result_summary"] = result
        if error is not None:
            updates["error_summary"] = error
        if attempt_count is not None:
            updates["attempt_count"] = attempt_count
        updated = task.model_copy(update=updates)
        graph.replace(updated)
        if self.store is not None:
            await asyncio.to_thread(self.store.save_task, updated)
        await self._emit(graph.run_id or "", updated.id, "task_status", status, message)
        return updated

    async def _cancel_task(self, graph: TaskGraph, task: AgentTask) -> AgentTask:
        current = graph.tasks[task.id]
        if current.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }:
            return current
        if current.status is TaskStatus.BLOCKED:
            return await self._set_task(graph, current, TaskStatus.CANCELLED, "Task cancelled")
        return await self._set_task(graph, current, TaskStatus.CANCELLED, "Task cancelled")

    async def _set_run(self, run: AgentRun, status: RunStatus, message: str) -> AgentRun:
        validate_run_transition(run.status, status)
        updated = run.model_copy(update={"status": status, "updated_at": utc_now()})
        graph = self._runs[run.id][1]
        self._runs[run.id] = (updated, graph)
        if self.store is not None:
            await asyncio.to_thread(self.store.save_run, updated)
        await self._emit(run.id, None, "run_status", status, message)
        return updated

    async def _emit(
        self,
        run_id: str,
        task_id: str | None,
        event_type: str,
        status: TaskStatus | RunStatus,
        message: str,
    ) -> None:
        self._sequences[run_id] += 1
        event = ProgressEvent(
            run_id=run_id,
            task_id=task_id,
            sequence=self._sequences[run_id],
            event_type=event_type,
            status=status,
            message=message,
        )
        if self.store is not None:
            event = await asyncio.to_thread(self.store.append_event, event)
            self._sequences[run_id] = event.sequence
        await self.events.publish(event)
