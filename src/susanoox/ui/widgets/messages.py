from __future__ import annotations

from typing import Literal

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

MessageKind = Literal["user", "assistant", "activity", "error"]


class MessageBubble(Static):
    def __init__(self, content: str, *, kind: MessageKind) -> None:
        super().__init__(classes=f"message {kind}")
        self._content = content
        self.kind = kind

    def compose(self) -> ComposeResult:
        labels = {
            "user": "› YOU",  # noqa: RUF001 - intentional prompt glyph
            "assistant": "◆ SUSANOOX",
            "activity": "◇ CONTEXT",
            "error": "× ERROR",  # noqa: RUF001 - intentional error glyph
        }
        yield Static(labels[self.kind], classes="message-label")
        yield Static(Markdown(self._content), classes="message-content")

    @property
    def markdown_text(self) -> str:
        return self._content

    async def update_content(self, content: str) -> None:
        self._content = content
        # A stable renderable avoids cancelling Textual child-widget removal during streaming.
        self.query_one(".message-content", Static).update(Markdown(content))


class ConversationView(VerticalScroll):
    async def add_message(self, content: str, *, kind: MessageKind) -> MessageBubble:
        message = MessageBubble(content, kind=kind)
        await self.mount(message)
        self.scroll_end(animate=False)
        return message
