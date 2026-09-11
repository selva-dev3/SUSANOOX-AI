from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import ValidationError

from susanoox.agent.orchestration.graph import TaskGraph
from susanoox.agent.orchestration.models import (
    AgentRun,
    BackgroundStatus,
    BackgroundTask,
    ProgressEvent,
    RecoveryEvent,
    RunStatus,
    SubAgent,
    TaskAttempt,
    TaskDependency,
)
from susanoox.agent.types import AgentTask, TaskStatus
from susanoox.security.redaction import redact_secrets
from susanoox.utils.errors import SessionError


class OrchestrationStore:
    """Durable task state stored beside the owning conversation session."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save_graph(self, run: AgentRun, graph: TaskGraph) -> None:
        safe_run = run.model_copy(update={"objective": redact_secrets(run.objective)})
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO agent_runs(id, session_id, status, payload) VALUES (?, ?, ?, ?)",
                    (safe_run.id, safe_run.session_id, safe_run.status, safe_run.model_dump_json()),
                )
                connection.executemany(
                    """INSERT INTO agent_tasks
                    (id, run_id, parent_task_id, status, priority, payload)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    [self._task_row(task) for task in graph.tasks.values()],
                )
                connection.executemany(
                    """INSERT INTO agent_dependencies
                    (run_id, predecessor_id, successor_id, payload) VALUES (?, ?, ?, ?)""",
                    [
                        (run.id, edge.predecessor_id, edge.successor_id, edge.model_dump_json())
                        for edge in graph.dependencies
                    ],
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the agent task graph.") from error

    def save_run(self, run: AgentRun) -> None:
        self.save_run_state(run)

    def save_run_state(self, run: AgentRun, tasks: tuple[AgentTask, ...] = ()) -> None:
        """Atomically persist a run transition and any associated task transitions."""
        safe = run.model_copy(update={"objective": redact_secrets(run.objective)})
        try:
            with self._connect() as connection:
                result = connection.execute(
                    "UPDATE agent_runs SET status = ?, payload = ? WHERE id = ?",
                    (safe.status, safe.model_dump_json(), safe.id),
                )
                if result.rowcount != 1:
                    raise SessionError("The agent run no longer exists.")
                for task in tasks:
                    task_result = connection.execute(
                        """UPDATE agent_tasks
                        SET parent_task_id = ?, status = ?, priority = ?, payload = ?
                        WHERE id = ? AND run_id = ?""",
                        (*self._task_update_row(task), run.id),
                    )
                    if task_result.rowcount != 1:
                        raise SessionError("An agent task no longer exists.")
        except sqlite3.Error as error:
            raise SessionError("Unable to update the agent run.") from error

    def save_task(self, task: AgentTask) -> None:
        try:
            with self._connect() as connection:
                result = connection.execute(
                    """UPDATE agent_tasks
                    SET parent_task_id = ?, status = ?, priority = ?, payload = ?
                    WHERE id = ?""",
                    self._task_update_row(task),
                )
                if result.rowcount != 1:
                    raise SessionError("The agent task no longer exists.")
        except sqlite3.Error as error:
            raise SessionError("Unable to update the agent task.") from error

    def add_attempt(self, attempt: TaskAttempt) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO agent_task_attempts(id, task_id, ordinal, payload)
                    VALUES (?, ?, ?, ?)""",
                    (attempt.id, attempt.task_id, attempt.ordinal, attempt.model_dump_json()),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the task attempt.") from error

    def add_recovery_event(self, event: RecoveryEvent) -> None:
        safe = event.model_copy(
            update={
                "category": redact_secrets(event.category),
                "action": redact_secrets(event.action),
                "outcome": redact_secrets(event.outcome or "") or None,
            }
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO agent_recovery_events(id, run_id, task_id, payload)
                    VALUES (?, ?, ?, ?)""",
                    (safe.id, safe.run_id, safe.task_id, safe.model_dump_json()),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the recovery event.") from error

    def save_subagent(self, agent: SubAgent) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT OR REPLACE INTO agent_subagents
                    (id, run_id, task_id, status, payload) VALUES (?, ?, ?, ?, ?)""",
                    (
                        agent.id,
                        agent.run_id,
                        agent.parent_task_id,
                        agent.status,
                        agent.model_dump_json(),
                    ),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the sub-agent state.") from error

    def save_background_task(self, task: BackgroundTask) -> None:
        safe = task.model_copy(
            update={
                "title": redact_secrets(task.title),
                "checkpoint": redact_secrets(task.checkpoint or "") or None,
                "result_summary": redact_secrets(task.result_summary or "") or None,
            }
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT OR REPLACE INTO agent_background_tasks
                    (id, session_id, run_id, task_id, status, payload)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        safe.id,
                        safe.session_id,
                        safe.run_id,
                        safe.task_id,
                        safe.status,
                        safe.model_dump_json(),
                    ),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the background task.") from error

    def list_background_tasks(
        self, *, session_id: str | None = None, limit: int = 20
    ) -> tuple[BackgroundTask, ...]:
        try:
            with self._connect() as connection:
                if session_id is None:
                    rows = connection.execute(
                        "SELECT payload FROM agent_background_tasks ORDER BY rowid DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """SELECT payload FROM agent_background_tasks
                        WHERE session_id = ? ORDER BY rowid DESC LIMIT ?""",
                        (session_id, limit),
                    ).fetchall()
            return tuple(BackgroundTask.model_validate_json(row[0]) for row in rows)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored background tasks are invalid or unreadable.") from error

    def list_subagents(self, run_id: str, *, limit: int = 20) -> tuple[SubAgent, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT payload FROM agent_subagents
                    WHERE run_id = ? ORDER BY rowid DESC LIMIT ?""",
                    (run_id, limit),
                ).fetchall()
            return tuple(SubAgent.model_validate_json(row[0]) for row in rows)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored sub-agent state is invalid or unreadable.") from error

    def append_event(self, event: ProgressEvent) -> ProgressEvent:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_events WHERE run_id = ?",
                    (event.run_id,),
                ).fetchone()
                sequenced = event.model_copy(update={"sequence": int(row[0])})
                safe = sequenced.model_copy(update={"message": redact_secrets(sequenced.message)})
                connection.execute(
                    "INSERT INTO agent_events(run_id, sequence, payload) VALUES (?, ?, ?)",
                    (safe.run_id, safe.sequence, safe.model_dump_json()),
                )
            return safe
        except sqlite3.Error as error:
            raise SessionError("Unable to save agent progress.") from error

    def load_run(self, run_id: str) -> tuple[AgentRun, TaskGraph] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    return None
                task_rows = connection.execute(
                    "SELECT payload FROM agent_tasks WHERE run_id = ?", (run_id,)
                ).fetchall()
                dependency_rows = connection.execute(
                    "SELECT payload FROM agent_dependencies WHERE run_id = ?", (run_id,)
                ).fetchall()
            run = AgentRun.model_validate_json(row[0])
            tasks = tuple(AgentTask.model_validate_json(item[0]) for item in task_rows)
            dependencies = tuple(
                TaskDependency.model_validate_json(item[0]) for item in dependency_rows
            )
            return run, TaskGraph(tasks, dependencies)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored agent run is invalid or unreadable.") from error

    def list_runs(self, session_id: str, *, limit: int = 20) -> tuple[AgentRun, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT payload FROM agent_runs
                    WHERE session_id = ? ORDER BY rowid DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            return tuple(AgentRun.model_validate_json(row[0]) for row in rows)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored agent runs are invalid or unreadable.") from error

    def load_events(self, run_id: str, *, limit: int = 100) -> tuple[ProgressEvent, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT payload FROM agent_events WHERE run_id = ?
                    ORDER BY sequence DESC LIMIT ?""",
                    (run_id, limit),
                ).fetchall()
            return tuple(ProgressEvent.model_validate_json(row[0]) for row in reversed(rows))
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored agent progress is invalid or unreadable.") from error

    def interrupt_active(self) -> int:
        interrupted = 0
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM agent_runs WHERE status = ?", (RunStatus.RUNNING,)
                ).fetchall()
                for row in rows:
                    run = AgentRun.model_validate_json(row[0]).model_copy(
                        update={"status": RunStatus.INTERRUPTED}
                    )
                    connection.execute(
                        "UPDATE agent_runs SET status = ?, payload = ? WHERE id = ?",
                        (run.status, run.model_dump_json(), run.id),
                    )
                    task_rows = connection.execute(
                        """SELECT payload FROM agent_tasks WHERE run_id = ?
                        AND status IN (?, ?, ?)""",
                        (
                            run.id,
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                            TaskStatus.RETRYING,
                        ),
                    ).fetchall()
                    for task_row in task_rows:
                        task = AgentTask.model_validate_json(task_row[0]).model_copy(
                            update={"status": TaskStatus.INTERRUPTED}
                        )
                        connection.execute(
                            "UPDATE agent_tasks SET status = ?, payload = ? WHERE id = ?",
                            (task.status, task.model_dump_json(), task.id),
                        )
                    interrupted += 1
                background_rows = connection.execute(
                    """SELECT payload FROM agent_background_tasks
                    WHERE status IN (?, ?, ?)""",
                    (
                        BackgroundStatus.QUEUED,
                        BackgroundStatus.RUNNING,
                        BackgroundStatus.PAUSED,
                    ),
                ).fetchall()
                for background_row in background_rows:
                    task = BackgroundTask.model_validate_json(background_row[0]).model_copy(
                        update={"status": BackgroundStatus.INTERRUPTED}
                    )
                    connection.execute(
                        """UPDATE agent_background_tasks SET status = ?, payload = ?
                        WHERE id = ?""",
                        (task.status, task.model_dump_json(), task.id),
                    )
            return interrupted
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Unable to reconcile interrupted agent runs.") from error

    @staticmethod
    def _task_row(task: AgentTask) -> tuple[str, str, str | None, str, int, str]:
        if task.run_id is None:
            raise ValueError("A persisted task must belong to a run")
        safe = task.model_copy(
            update={
                "objective": redact_secrets(task.objective),
                "result_summary": redact_secrets(task.result_summary or "") or None,
                "error_summary": redact_secrets(task.error_summary or "") or None,
            }
        )
        run_id = safe.run_id
        if run_id is None:  # Defensive narrowing for future model changes.
            raise ValueError("A persisted task must belong to a run")
        return (
            safe.id,
            run_id,
            safe.parent_task_id,
            safe.status,
            safe.priority,
            safe.model_dump_json(),
        )

    @classmethod
    def _task_update_row(cls, task: AgentTask) -> tuple[str | None, str, int, str, str]:
        row = cls._task_row(task)
        return row[2], row[3], row[4], row[5], row[0]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
