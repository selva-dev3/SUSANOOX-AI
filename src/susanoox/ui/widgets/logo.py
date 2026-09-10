from __future__ import annotations

from rich.text import Text


def susanoox_mark() -> Text:
    """Return a portable terminal rendering of the supplied Susanoox mark."""
    mark = Text()
    mark.append("      ██\n", style="bold #ff0061")
    mark.append("    ████\n", style="bold #ff0061")
    mark.append("  ████\n", style="bold #ff0061")
    mark.append("████", style="bold #ad003f")
    return mark
