from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

CommandName = Literal[
    "model",
    "usage",
    "plan",
    "approve",
    "revise",
    "reject",
    "context",
    "tasks",
    "task",
    "agents",
    "cancel",
    "help",
    "clear",
    "exit",
    "paste-image",
]
COMMANDS: Final[dict[CommandName, str]] = {
    "model": "select a chat model",
    "usage": "show token usage for this session",
    "paste-image": "attach an image from the OS clipboard",
    "plan": "enable planning or create a plan: /plan <task>",
    "approve": "approve and continue with the current plan",
    "revise": "revise the current plan: /revise <feedback>",
    "reject": "cancel the current plan",
    "context": "inspect or change automatic context: /context [on|off|toggle]",
    "tasks": "show task checklists for this session",
    "task": "inspect a task checklist: /task <id>",
    "agents": "show bounded sub-agent activity",
    "cancel": "cancel a pending task checklist: /cancel <id>",
    "clear": "clear the conversation",
    "help": "show this command list",
    "exit": "close Susanoox",
}


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: CommandName
    argument: str | None


class UnknownCommandError(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown command: /{name}. Type /help for available commands.")


def parse_slash_command(value: str) -> SlashCommand | None:
    normalized = value.strip()
    if not normalized.startswith("/"):
        return None
    command_text, _, argument = normalized[1:].partition(" ")
    name = command_text.lower()
    if name not in COMMANDS:
        raise UnknownCommandError(name)
    return SlashCommand(name=name, argument=argument.strip() or None)


def help_text() -> str:
    return "**Commands**\n\n" + "\n".join(
        f"- `/{name}` — {description}" for name, description in COMMANDS.items()
    )
