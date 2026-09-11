from __future__ import annotations

from susanoox.agent.orchestration.plans import checklist_from_plan
from susanoox.agent.planner import PlanService
from susanoox.ui.widgets.task_progress import TaskProgressPanel


def test_task_progress_panel_renders_public_checklist_state() -> None:
    plan = PlanService().create(session_id="session", objective="Fix authentication")
    run, graph = checklist_from_plan(plan)
    panel = TaskProgressPanel()

    panel.show_graph(run, graph)

    rendered = str(panel.render())
    assert "Fix authentication" in rendered
    assert "0 / 6 complete" in rendered
    assert "Inspect the relevant implementation" in rendered
