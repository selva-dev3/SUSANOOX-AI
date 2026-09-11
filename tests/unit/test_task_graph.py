from __future__ import annotations

import pytest

from susanoox.agent.orchestration.graph import TaskGraph, TaskGraphError
from susanoox.agent.orchestration.models import AgentRun, TaskDependency, task_from_plan_step
from susanoox.agent.types import TaskStatus


def _tasks(count: int = 3):
    run = AgentRun(session_id="session", objective="Coordinate work")
    tasks = tuple(task_from_plan_step(run=run, title=f"Task {index}") for index in range(count))
    return run, tasks


def test_graph_rejects_cycles_and_unknown_dependencies() -> None:
    _run, tasks = _tasks(2)
    with pytest.raises(TaskGraphError, match="cycle"):
        TaskGraph(
            tasks,
            (
                TaskDependency(predecessor_id=tasks[0].id, successor_id=tasks[1].id),
                TaskDependency(predecessor_id=tasks[1].id, successor_id=tasks[0].id),
            ),
        )
    with pytest.raises(TaskGraphError, match="unknown"):
        TaskGraph(
            tasks,
            (TaskDependency(predecessor_id="missing", successor_id=tasks[0].id),),
        )


def test_graph_returns_only_dependency_ready_tasks() -> None:
    _run, tasks = _tasks(3)
    graph = TaskGraph(
        tasks,
        (
            TaskDependency(predecessor_id=tasks[0].id, successor_id=tasks[1].id),
            TaskDependency(predecessor_id=tasks[1].id, successor_id=tasks[2].id),
        ),
    )
    assert graph.ready() == (tasks[0],)

    graph.replace(tasks[0].model_copy(update={"status": TaskStatus.COMPLETED}))
    assert graph.ready() == (tasks[1],)


def test_graph_marks_failed_dependents_blocked_and_reports_progress() -> None:
    _run, tasks = _tasks(2)
    graph = TaskGraph(
        tasks,
        (TaskDependency(predecessor_id=tasks[0].id, successor_id=tasks[1].id),),
    )
    graph.replace(tasks[0].model_copy(update={"status": TaskStatus.FAILED}))

    assert graph.blocked_by_failure() == (tasks[1],)
    graph.replace(tasks[1].model_copy(update={"status": TaskStatus.BLOCKED}))
    assert graph.progress().blocked == 1
    assert not graph.terminal


def test_graph_rejects_invalid_parent_hierarchy() -> None:
    _run, tasks = _tasks(2)
    invalid = tasks[0].model_copy(update={"parent_task_id": "missing"})
    with pytest.raises(TaskGraphError, match="parent"):
        TaskGraph((invalid, tasks[1]))

    parent = tasks[0].model_copy(update={"parent_task_id": tasks[1].id})
    child = tasks[1].model_copy(update={"parent_task_id": tasks[0].id})
    with pytest.raises(TaskGraphError, match="cycle"):
        TaskGraph((parent, child))
