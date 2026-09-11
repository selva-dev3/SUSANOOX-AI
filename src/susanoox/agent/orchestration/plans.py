from __future__ import annotations

from susanoox.agent.orchestration.graph import TaskGraph
from susanoox.agent.orchestration.models import (
    AgentRun,
    RunStatus,
    TaskDependency,
    task_from_plan_step,
)
from susanoox.agent.types import ExecutionPlan, PlanStatus, TaskBudget, TaskStatus


def checklist_from_plan(
    plan: ExecutionPlan, *, budget: TaskBudget | None = None
) -> tuple[AgentRun, TaskGraph]:
    """Compile a visible plan into durable public task state, not model reasoning."""
    run_status = {
        PlanStatus.AWAITING_APPROVAL: RunStatus.WAITING_APPROVAL,
        # Approved UI plans are durable checklists, not executable runs. Concrete
        # tool workers are connected separately through permission capabilities.
        PlanStatus.APPROVED: RunStatus.PLANNED,
        PlanStatus.CANCELLED: RunStatus.CANCELLED,
        PlanStatus.SUPERSEDED: RunStatus.CANCELLED,
    }[plan.status]
    run = AgentRun(
        session_id=plan.session_id,
        objective=plan.objective,
        status=run_status,
        plan_id=plan.id,
        budget=budget or TaskBudget(),
    )
    task_status = TaskStatus.CANCELLED if run_status is RunStatus.CANCELLED else TaskStatus.PENDING
    tasks = tuple(
        task_from_plan_step(run=run, title=step.title, priority=-step.ordinal).model_copy(
            update={"status": task_status}
        )
        for step in plan.steps
    )
    task_by_step = {step.id: task for step, task in zip(plan.steps, tasks, strict=True)}
    dependencies: list[TaskDependency] = []
    for index, (step, task) in enumerate(zip(plan.steps, tasks, strict=True)):
        unknown = set(step.dependencies) - task_by_step.keys()
        if unknown:
            raise ValueError("A plan step depends on an unknown step")
        explicit = tuple(
            TaskDependency(
                predecessor_id=task_by_step[dependency].id,
                successor_id=task.id,
            )
            for dependency in step.dependencies
        )
        if explicit:
            dependencies.extend(explicit)
        elif index:
            dependencies.append(
                TaskDependency(predecessor_id=tasks[index - 1].id, successor_id=task.id)
            )
    return run, TaskGraph(tasks, dependencies)
