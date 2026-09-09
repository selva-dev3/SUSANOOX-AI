from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class AppHeader(Horizontal):
    def __init__(self, *, version: str, model: str, project_path: Path) -> None:
        super().__init__(id="app-header")
        self._version = version
        self._model = model
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(("SUSANOOX", "bold #df7652"), f"  v{self._version}"), id="brand")
        yield Static(f"{self._model}  ·  ● connected", id="connection-status")
        yield Static(Text(str(self._project_path)), id="project-path")
