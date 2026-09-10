from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from susanoox.commands import COMMANDS, CommandName


class CommandSuggestions(OptionList):
    """Non-focusable command picker; the prompt retains keyboard ownership."""

    can_focus = False

    def __init__(self) -> None:
        super().__init__(id="command-suggestions")
        self.matches: tuple[CommandName, ...] = ()

    def suggest(self, text: str) -> None:
        prefix = text[1:].lower()
        if not text.startswith("/") or any(c not in "abcdefghijklmnopqrstuvwxyz-" for c in prefix):
            self.display = False
            return
        self.matches = tuple(name for name in COMMANDS if name.startswith(prefix))
        self.clear_options()
        self.add_options(
            [Option(Text(f"/{name}  ·  {COMMANDS[name]}"), id=name) for name in self.matches]
            or [Option("No matching commands", disabled=True)]
        )
        self.highlighted = 0 if self.matches else None
        self.display = True

    def move(self, direction: int) -> None:
        if self.matches:
            self.highlighted = ((self.highlighted or 0) + direction) % len(self.matches)

    @property
    def selected_command(self) -> str | None:
        index = self.highlighted
        return self.matches[index] if index is not None and index < len(self.matches) else None
