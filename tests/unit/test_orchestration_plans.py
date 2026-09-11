from __future__ import annotations

from susanoox.agent.orchestration.models import RunStatus
from susanoox.agent.orchestration.plans import checklist_from_plan
from susanoox.agent.planner import PlanService
from susanoox.agent.types import PlanStatus, TaskStatus


def test_visible_plan_compiles_to_ordered_durable_checklist() -> None:
    plan = PlanService().create(session_id="session", objective="Fix authentication")

    run, graph = checklist_from_plan(plan)

    assert run.plan_id == plan.id
    assert run.status is RunStatus.WAITING_APPROVAL
    assert len(graph.tasks) == len(plan.steps)
    assert len(graph.dependencies) == len(plan.steps) - 1
    assert all(task.status is TaskStatus.PENDING for task in graph.tasks.values())


def test_approved_plan_is_a_non_executable_planned_checklist() -> None:
    service = PlanService()
    approved = service.approve(service.create(session_id="session", objective="Fix auth"))

    run, _graph = checklist_from_plan(approved)

    assert approved.status is PlanStatus.APPROVED
    assert run.status is RunStatus.PLANNED
