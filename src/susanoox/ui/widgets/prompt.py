from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static, TextArea


class PromptComposer(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("›", id="prompt-mark")  # noqa: RUF001 - intentional prompt glyph
        yield TextArea(
            id="prompt-input",
            soft_wrap=True,
            show_line_numbers=False,
            placeholder='Try "fix the failing tests"',
        )
        yield Button("Send", id="send-button", variant="primary")

    @property
    def text(self) -> str:
        return self.query_one(TextArea).text

    def clear(self) -> None:
        self.query_one(TextArea).clear()

    def set_enabled(self, enabled: bool) -> None:
        self.query_one(TextArea).disabled = not enabled
        self.query_one(Button).disabled = not enabled

    def focus_input(self) -> None:
        self.query_one(TextArea).focus()
