from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from susanoox.agent.orchestration.graph import TaskGraph
from susanoox.agent.orchestration.models import (
    AgentRun,
    BackgroundStatus,
    BackgroundTask,
    RunStatus,
    task_from_plan_step,
)
from susanoox.agent.types import TaskStatus
from susanoox.config.settings import DEFAULT_MODEL
from susanoox.sessions.orchestration_storage import OrchestrationStore
from susanoox.sessions.storage import SessionStore
from susanoox.utils.errors import SessionError


def _stores(tmp_path: Path) -> tuple[SessionStore, OrchestrationStore, str]:
    path = tmp_path / "sessions.sqlite3"
    sessions = SessionStore(path)
    sessions.initialize()
    session = sessions.create(project_root=tmp_path, model=DEFAULT_MODEL)
    return sessions, OrchestrationStore(path), session.id


def test_schema_upgrade_creates_orchestration_tables(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '1')")

    SessionStore(path).initialize()

    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert version == ("2",)
    assert {"agent_runs", "agent_tasks", "agent_events"} <= tables


def test_run_graph_round_trip_and_secret_redaction(tmp_path: Path) -> None:
    _sessions, store, session_id = _stores(tmp_path)
    run = AgentRun(session_id=session_id, objective="Use sk-forge-supersecret")
    task = task_from_plan_step(run=run, title="Inspect sk-forge-supersecret")
    graph = TaskGraph((task,))

    store.save_graph(run, graph)
    loaded = store.load_run(run.id)

    assert loaded is not None
    loaded_run, loaded_graph = loaded
    assert "supersecret" not in loaded_run.objective
    assert "supersecret" not in loaded_graph.tasks[task.id].objective


def test_active_runs_are_marked_interrupted_on_recovery(tmp_path: Path) -> None:
    _sessions, store, session_id = _stores(tmp_path)
    run = AgentRun(session_id=session_id, objective="Resume", status=RunStatus.RUNNING)
    task = task_from_plan_step(run=run, title="Work").model_copy(
        update={"status": TaskStatus.RUNNING}
    )
    store.save_graph(run, TaskGraph((task,)))

    assert store.interrupt_active() == 1
    loaded = store.load_run(run.id)

    assert loaded is not None
    assert loaded[0].status is RunStatus.INTERRUPTED
    assert loaded[1].tasks[task.id].status is TaskStatus.INTERRUPTED


def test_run_and_task_transition_rolls_back_atomically(tmp_path: Path) -> None:
    _sessions, store, session_id = _stores(tmp_path)
    run = AgentRun(session_id=session_id, objective="Atomic update")
    task = task_from_plan_step(run=run, title="Existing")
    store.save_graph(run, TaskGraph((task,)))
    missing = task.model_copy(update={"id": "missing", "status": TaskStatus.CANCELLED})
    cancelled_run = run.model_copy(update={"status": RunStatus.CANCELLED})

    with pytest.raises(SessionError, match="no longer exists"):
        store.save_run_state(cancelled_run, (missing,))

    loaded = store.load_run(run.id)
    assert loaded is not None
    assert loaded[0].status is RunStatus.PENDING


def test_background_tasks_are_isolated_by_session(tmp_path: Path) -> None:
    sessions, store, session_id = _stores(tmp_path)
    other = sessions.create(project_root=tmp_path, model=DEFAULT_MODEL)
    store.save_background_task(BackgroundTask(session_id=session_id, title="Tests"))
    store.save_background_task(BackgroundTask(session_id=other.id, title="Index"))

    tasks = store.list_background_tasks(session_id=session_id)

    assert len(tasks) == 1
    assert tasks[0].title == "Tests"


@pytest.mark.parametrize(
    "status",
    [BackgroundStatus.QUEUED, BackgroundStatus.RUNNING, BackgroundStatus.PAUSED],
)
def test_nonterminal_background_tasks_are_interrupted_on_recovery(
    tmp_path: Path, status: BackgroundStatus
) -> None:
    _sessions, store, session_id = _stores(tmp_path)
    task = BackgroundTask(session_id=session_id, title="Work", status=status)
    store.save_background_task(task)

    store.interrupt_active()

    restored = store.list_background_tasks(session_id=session_id)
    assert restored[0].status is BackgroundStatus.INTERRUPTED
