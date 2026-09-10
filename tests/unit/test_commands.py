from __future__ import annotations

import pytest

from susanoox.commands import UnknownCommandError, parse_slash_command


def test_plain_prompt_is_not_a_command() -> None:
    assert parse_slash_command("Explain /model handling") is None


def test_command_name_is_normalized_and_argument_is_preserved() -> None:
    command = parse_slash_command("  /MODEL susanoox-large  ")

    assert command is not None
    assert command.name == "model"
    assert command.argument == "susanoox-large"


def test_unknown_command_is_rejected_locally() -> None:
    with pytest.raises(UnknownCommandError, match="/unknown"):
        parse_slash_command("/unknown")


@pytest.mark.parametrize("name", ["plan", "approve", "revise", "reject", "context"])
def test_agent_intelligence_commands_are_available(name: str) -> None:
    command = parse_slash_command(f"/{name}")

    assert command is not None
    assert command.name == name


@pytest.mark.parametrize("argument", ["on", "off", "toggle"])
def test_context_command_preserves_toggle_argument(argument: str) -> None:
    command = parse_slash_command(f"/context {argument}")

    assert command is not None
    assert command.name == "context"
    assert command.argument == argument
