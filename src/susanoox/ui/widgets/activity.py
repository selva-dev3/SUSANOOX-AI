from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import LoadingIndicator, Static


class ActivityBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="activity-spinner")
        yield Static("Ready", id="activity-label")

    def set_activity(self, message: str, *, busy: bool) -> None:
        self.query_one("#activity-label", Static).update(message)
        self.set_class(busy, "busy")
