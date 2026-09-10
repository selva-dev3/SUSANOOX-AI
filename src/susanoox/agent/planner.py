from __future__ import annotations

from susanoox.agent.types import ExecutionPlan, PlanStatus, PlanStep, utc_now
from susanoox.context.models import ContextSnapshot
from susanoox.utils.errors import PlanError


class PlanService:
    """Creates and transitions concise visible plans, never private model reasoning."""

    def create(
        self,
        *,
        session_id: str,
        objective: str,
        context: ContextSnapshot | None = None,
        version: int = 1,
    ) -> ExecutionPlan:
        normalized = " ".join(objective.split())
        if not normalized:
            raise PlanError("A plan needs a task. Use `/plan <task>`.")
        if len(normalized) > 2_000:
            raise PlanError("The planning task is too long. Keep it under 2,000 characters.")
        selected = (", ".join(item.path for item in context.files[:4])[:400]) if context else ""
        suffix = f": {selected}" if selected else ""
        inspect_result = f"Relevant implementation is understood{suffix}."
        steps = (
            PlanStep(
                ordinal=1,
                title="Inspect the relevant implementation",
                expected_result=inspect_result,
            ),
            PlanStep(
                ordinal=2,
                title="Trace behavior, constraints, and failure paths",
                expected_result="The root cause and safe change boundary are identified.",
            ),
            PlanStep(
                ordinal=3,
                title="Apply the smallest correct implementation change",
                expected_result="The requested behavior is implemented without unrelated rewrites.",
            ),
            PlanStep(
                ordinal=4,
                title="Add or update focused regression tests",
                expected_result="The requested behavior and important edge cases are covered.",
            ),
            PlanStep(
                ordinal=5,
                title="Run relevant validation",
                expected_result="Focused tests and available quality checks pass.",
            ),
            PlanStep(
                ordinal=6,
                title="Review the final diff and report remaining risks",
                expected_result="Only intended changes remain and assumptions are explicit.",
            ),
        )
        return ExecutionPlan(
            session_id=session_id,
            version=version,
            objective=normalized,
            steps=steps,
            context_snapshot_id=context.id if context else None,
            validation_strategy=("Run focused tests", "Inspect the final diff"),
        )

    def approve(self, plan: ExecutionPlan) -> ExecutionPlan:
        if plan.status is not PlanStatus.AWAITING_APPROVAL:
            raise PlanError(f"The current plan cannot be approved while it is {plan.status}.")
        return plan.model_copy(update={"status": PlanStatus.APPROVED, "updated_at": utc_now()})

    def reject(self, plan: ExecutionPlan) -> ExecutionPlan:
        if plan.status is not PlanStatus.AWAITING_APPROVAL:
            raise PlanError(f"The current plan cannot be rejected while it is {plan.status}.")
        return plan.model_copy(update={"status": PlanStatus.CANCELLED, "updated_at": utc_now()})

    def revise(
        self,
        plan: ExecutionPlan,
        feedback: str,
        *,
        context: ContextSnapshot | None = None,
    ) -> ExecutionPlan:
        objective = self.revision_objective(plan, feedback)
        return self.create(
            session_id=plan.session_id,
            objective=objective,
            context=context,
            version=plan.version + 1,
        )

    @staticmethod
    def revision_objective(plan: ExecutionPlan, feedback: str) -> str:
        normalized = " ".join(feedback.split())
        if not normalized:
            raise PlanError("Revision feedback cannot be empty.")
        return f"{plan.objective}\nRevision requested: {normalized}"

    @staticmethod
    def render(plan: ExecutionPlan) -> str:
        lines = ["**◆ PLAN**", "", f"**Objective:** {plan.objective}", ""]
        lines.extend(f"{step.ordinal}. {step.title}" for step in plan.steps)
        lines.extend(
            ("", "Approve with `/approve`, revise with `/revise <feedback>`, or `/reject`.")
        )
        return "\n".join(lines)
