from __future__ import annotations

import pytest

from susanoox.agent.planner import PlanService
from susanoox.agent.types import PlanStatus
from susanoox.utils.errors import PlanError


def test_plan_requires_approval_and_has_bounded_visible_steps() -> None:
    service = PlanService()

    plan = service.create(session_id="session", objective="Fix login validation")

    assert plan.status is PlanStatus.AWAITING_APPROVAL
    assert 1 <= len(plan.steps) <= 20
    assert "Fix login validation" in service.render(plan)
    assert "reasoning" not in service.render(plan).casefold()


def test_plan_lifecycle_requires_valid_state() -> None:
    service = PlanService()
    plan = service.create(session_id="session", objective="Add tests")
    approved = service.approve(plan)

    assert approved.status is PlanStatus.APPROVED
    with pytest.raises(PlanError, match="cannot be approved"):
        service.approve(approved)


def test_revision_creates_new_plan_version() -> None:
    service = PlanService()
    plan = service.create(session_id="session", objective="Change API")

    revised = service.revise(plan, "Preserve backward compatibility")

    assert revised.version == 2
    assert "Preserve backward compatibility" in revised.objective
