from __future__ import annotations

from textual.widgets import Static

from susanoox.agent.orchestration.graph import TaskGraph
from susanoox.agent.orchestration.models import AgentRun, RunStatus
from susanoox.agent.types import TaskStatus

_MARKERS = {
    TaskStatus.PENDING: "○",
    TaskStatus.QUEUED: "◉",
    TaskStatus.RUNNING: "⠋",
    TaskStatus.WAITING_APPROVAL: "◇",
    TaskStatus.BLOCKED: "⚠",
    TaskStatus.RETRYING: "↻",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.CANCELLED: "■",
    TaskStatus.SKIPPED: "-",
    TaskStatus.INTERRUPTED: "■",
}


class TaskProgressPanel(Static):
    """Compact rendering of public task state; hidden reasoning is never accepted."""

    def show_graph(self, run: AgentRun, graph: TaskGraph) -> None:
        progress = graph.progress()
        label = "PLANNED CHECKLIST" if run.status is RunStatus.PLANNED else "TASK"
        lines = [
            f"◆ {label} · {run.objective}",
            f"  {progress.succeeded} / {progress.total} complete · {run.status}",
        ]
        tasks = sorted(graph.tasks.values(), key=lambda item: (-item.priority, item.created_at))
        for task in tasks[:6]:
            lines.append(f"  {_MARKERS[task.status]} {task.objective}")
        if len(tasks) > 6:
            lines.append(f"  … {len(tasks) - 6} more · use /task {run.id[:8]}")
        self.update("\n".join(lines))
        self.display = True

    def clear_graph(self) -> None:
        self.update("")
        self.display = False
