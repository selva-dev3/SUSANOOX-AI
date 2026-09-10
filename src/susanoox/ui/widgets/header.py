from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class AppHeader(Horizontal):
    def __init__(
        self, *, version: str, model: str, project_path: Path, auto_context_enabled: bool
    ) -> None:
        super().__init__(id="app-header")
        self._version = version
        self._model = model
        self._project_path = project_path
        self._auto_context_enabled = auto_context_enabled

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(("SUSANOOX", "bold #df7652"), f"  v{self._version}"), id="brand")
        yield Static(self._status_text(), id="connection-status")
        yield Static(Text(str(self._project_path)), id="project-path")

    def set_model(self, model: str) -> None:
        self._model = model
        self.query_one("#connection-status", Static).update(self._status_text())

    def set_auto_context(self, enabled: bool) -> None:
        self._auto_context_enabled = enabled
        self.query_one("#connection-status", Static).update(self._status_text())

    def _status_text(self) -> str:
        context = "context on" if self._auto_context_enabled else "context off"
        return f"{self._model}  ·  ● connected  ·  {context}"
