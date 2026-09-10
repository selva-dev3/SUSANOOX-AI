from __future__ import annotations

from textual.app import App, ComposeResult

from susanoox.ui.widgets.command_suggestions import CommandSuggestions
from susanoox.ui.widgets.messages import MessageBubble, SelectableMarkdown
from susanoox.ui.widgets.prompt import PromptComposer


class CopyTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield MessageBubble("Copy this response", kind="assistant")
        yield CommandSuggestions()
        yield PromptComposer()


async def test_mouse_selected_response_can_be_copied_with_prompt_focused() -> None:
    app = CopyTestApp()

    async with app.run_test(size=(80, 20)) as pilot:
        app.query_one(PromptComposer).focus_input()
        content = app.query_one(SelectableMarkdown)

        await pilot.mouse_down(content, (0, 0))
        await pilot.hover(content, (8, 0))
        await pilot.mouse_up(content, (8, 0))
        await pilot.pause()

        assert app.screen.get_selected_text() == "Copy this"
        await pilot.press("ctrl+c")
        assert app.clipboard == "Copy this"
