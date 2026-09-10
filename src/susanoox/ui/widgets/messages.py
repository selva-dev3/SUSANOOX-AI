from __future__ import annotations

from itertools import pairwise
from typing import Literal

from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual
from textual.widgets import Static

MessageKind = Literal["user", "assistant", "activity", "error"]


class _SelectableRichVisual(RichVisual):
    """Rich rendering with the offsets Textual needs for text selection."""

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        strips = super().render_strips(width, height, style, options)
        selection = options.selection
        selection_style = options.selection_style
        rendered: list[Strip] = []

        for y, strip in enumerate(strips):
            selected_span = selection.get_span(y) if selection is not None else None
            selected_start = selected_span[0] if selected_span is not None else None
            selected_end = selected_span[1] if selected_span is not None else None
            segments: list[Segment] = []
            line_offset = 0

            for segment in strip:
                text, segment_style, control = segment
                if control is not None or not text:
                    segments.append(segment)
                    continue

                start = line_offset
                end = start + len(text)
                cuts = {start, end}
                if selected_start is not None and selected_end is not None:
                    effective_selected_end = end if selected_end == -1 else selected_end
                    cuts.update(
                        {
                            max(start, min(end, selected_start)),
                            max(start, min(end, effective_selected_end)),
                        }
                    )

                base_style = segment_style or RichStyle()
                ordered_cuts = sorted(cuts)
                for part_start, part_end in pairwise(ordered_cuts):
                    if part_start == part_end:
                        continue
                    part_style = base_style
                    if (
                        selected_start is not None
                        and selected_end is not None
                        and selection_style is not None
                        and part_start >= selected_start
                        and (selected_end == -1 or part_end <= selected_end)
                    ):
                        part_style += selection_style.rich_style
                    part_style += RichStyle(meta={"offset": (part_start, y)})
                    segments.append(
                        Segment(
                            text[part_start - start : part_end - start],
                            part_style,
                            control,
                        )
                    )
                line_offset = end

            rendered.append(Strip(segments))

        return rendered


class SelectableMarkdown(Static):
    """Rich Markdown that exposes its rendered terminal text for mouse selection."""

    ALLOW_SELECT = True

    def render(self) -> _SelectableRichVisual:
        content = self.content
        if not isinstance(content, Markdown):
            raise TypeError("SelectableMarkdown requires Rich Markdown content")
        return _SelectableRichVisual(self, content)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        lines = [self.render_line(y).text.rstrip() for y in range(self.size.height)]
        if not lines:
            return None
        return selection.extract("\n".join(lines)), "\n"


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
        yield SelectableMarkdown(Markdown(self._content), classes="message-content")

    @property
    def markdown_text(self) -> str:
        return self._content

    async def update_content(self, content: str) -> None:
        self._content = content
        # A stable renderable avoids cancelling Textual child-widget removal during streaming.
        self.query_one(".message-content", SelectableMarkdown).update(Markdown(content))


class ConversationView(VerticalScroll):
    async def add_message(self, content: str, *, kind: MessageKind) -> MessageBubble:
        message = MessageBubble(content, kind=kind)
        await self.mount(message)
        self.scroll_end(animate=False)
        return message
