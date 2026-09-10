from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static, TextArea

from susanoox.models.protocol import ImageAttachment
from susanoox.ui.widgets.command_suggestions import CommandSuggestions

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def pasted_image_path(text: str) -> Path | None:
    value = text.strip()
    if any(character in value for character in "\r\n\x00"):
        return None
    quoted = len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]
    if quoted:
        value = value[1:-1]
    # Intercept explicit paths only; ordinary filenames/prose remain editable text.
    candidate = Path(value)
    explicit = candidate.is_absolute() or value.startswith(("./", "../", "~/", ".\\", "..\\"))
    if not explicit and not quoted:
        return None
    if not quoted and not candidate.is_absolute() and any(c.isspace() for c in value):
        return None
    return candidate if candidate.suffix.lower() in _IMAGE_SUFFIXES else None


class PromptInput(TextArea):
    class Submitted(Message):
        pass

    class ImagePathPasted(Message):
        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    def on_key(self, event: events.Key) -> None:
        if self.disabled or self.read_only:
            return
        menu = self.screen.query_one(CommandSuggestions)
        if menu.display and event.key in {"up", "down", "tab", "enter", "escape"}:
            event.stop()
            event.prevent_default()
            if event.key in {"up", "down"}:
                menu.move(-1 if event.key == "up" else 1)
            else:
                if event.key != "escape" and menu.selected_command is not None:
                    self.load_text(f"/{menu.selected_command} ")
                    self.move_cursor(self.document.end)
                menu.display = False
            return
        if event.is_printable or event.key in {"backspace", "delete"}:
            self.call_after_refresh(self.refresh_suggestions)
        if event.key in {"enter", "ctrl+enter"}:
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted())
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.replace("\n", *self.selection, maintain_selection_offset=False)
            return

    def on_paste(self, event: events.Paste) -> None:
        if self.disabled or self.read_only:
            return
        candidate = pasted_image_path(event.text)
        if candidate is not None:
            self.screen.query_one(CommandSuggestions).display = False
            event.stop()
            event.prevent_default()
            self.post_message(self.ImagePathPasted(candidate))
            return
        self.call_after_refresh(self.refresh_suggestions)

    def refresh_suggestions(self) -> None:
        menu = self.screen.query_one(CommandSuggestions)
        if self.disabled or self.read_only:
            menu.display = False
        else:
            menu.suggest(self.text)


class PromptComposer(Horizontal):
    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._attachment: ImageAttachment | None = None

    def compose(self) -> ComposeResult:
        yield Static("›", id="prompt-mark")  # noqa: RUF001 - intentional prompt glyph
        yield Button("", id="attachment-button")
        yield PromptInput(
            id="prompt-input",
            soft_wrap=True,
            show_line_numbers=False,
            placeholder='Try "fix the failing tests"',
        )
        yield Button("Send", id="send-button", variant="primary")

    @on(TextArea.Changed)
    def prompt_changed(self) -> None:
        menu = self.screen.query_one(CommandSuggestions)
        if menu.display:
            self.query_one(PromptInput).refresh_suggestions()

    @property
    def text(self) -> str:
        return self.query_one(PromptInput).text

    @property
    def attachment(self) -> ImageAttachment | None:
        return self._attachment

    def clear(self) -> None:
        self.query_one(PromptInput).clear()
        self.screen.query_one(CommandSuggestions).display = False

    def set_attachment(self, attachment: ImageAttachment) -> None:
        self._attachment = attachment
        button = self.query_one("#attachment-button", Button)
        button.label = Text(f"× {attachment.display_name}")  # noqa: RUF001
        button.display = True

    def clear_attachment(self) -> None:
        self._attachment = None
        button = self.query_one("#attachment-button", Button)
        button.label = ""
        button.display = False

    def set_enabled(self, enabled: bool) -> None:
        self.query_one(PromptInput).disabled = not enabled
        if not enabled:
            self.screen.query_one(CommandSuggestions).display = False
        for button in self.query(Button):
            button.disabled = not enabled

    def focus_input(self) -> None:
        self.query_one(PromptInput).focus()
