from pathlib import Path

import pytest
from textual import events

from susanoox.commands import COMMANDS
from susanoox.config.credentials import Credential, CredentialSource
from susanoox.config.settings import Settings
from susanoox.ui.app import SusanooxApp
from susanoox.ui.widgets.command_suggestions import CommandSuggestions
from susanoox.ui.widgets.prompt import PromptInput
from tests.conftest import FakeChatClient
from tests.ui.test_app import MemoryCredentialStore


@pytest.mark.parametrize("size", [(100, 35), (40, 16)])
async def test_keyboard_completion(tmp_path: Path, size: tuple[int, int]) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path),
        credential_store=MemoryCredentialStore(Credential("test-only", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        menu = app.screen.query_one(CommandSuggestions)
        await pilot.press("/")
        await pilot.pause()
        assert menu.display
        assert menu.matches == tuple(COMMANDS)
        assert menu.region.bottom <= prompt.region.y
        await pilot.press("down")
        assert menu.selected_command == "usage"
        await pilot.press("up", "m", "o")
        await pilot.pause()
        assert menu.matches == ("model",)
        await pilot.press("enter")
        assert prompt.text == "/model "
        assert not menu.display
        assert app.focused is prompt
        assert not client.requests
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ModelPickerScreen"


async def test_dismiss_empty_arguments_and_chat(tmp_path: Path) -> None:
    client = FakeChatClient()
    app = SusanooxApp(
        settings=Settings(project_path=tmp_path),
        credential_store=MemoryCredentialStore(Credential("test-only", CredentialSource.KEYRING)),
        client_factory=lambda _key, _settings: client,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        menu = app.screen.query_one(CommandSuggestions)
        await pilot.press("/", "z", "z")
        await pilot.pause()
        assert menu.display and not menu.matches
        await pilot.press("escape")
        assert not menu.display and prompt.text == "/zz"
        prompt.clear()
        await pilot.press("/", "m", "tab")
        await pilot.pause()
        assert prompt.text == "/model " and not menu.display
        await pilot.press("s")
        await pilot.pause()
        assert not menu.display
        prompt.clear()
        await pilot.press("h", "i", "/", "x")
        await pilot.pause()
        assert not menu.display
        await pilot.press("enter")
        await pilot.pause()
        assert client.requests[-1][-1].content == "hi/x"
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("shift+enter")
        await pilot.pause()
        assert prompt.text == "/\n" and not menu.display
        prompt.clear()
        app.post_message(events.Paste(str(tmp_path / "example.txt")))
        await pilot.pause()
        assert not menu.display
