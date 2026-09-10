from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _native_clipboard_command() -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        return ["pbcopy"]
    if sys.platform == "win32" and shutil.which("clip"):
        return ["clip"]
    if sys.platform.startswith("linux"):
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
            return ["wl-copy"]
        if shutil.which("xclip"):
            return ["xclip", "-selection", "clipboard"]
        if shutil.which("xsel"):
            return ["xsel", "--clipboard", "--input"]
    return None


def copy_to_system_clipboard(text: str) -> bool:
    """Copy text with an available native helper without invoking a shell."""
    command = _native_clipboard_command()
    if command is None:
        return False
    try:
        subprocess.run(  # noqa: S603 - command is selected from a fixed allowlist
            command,
            input=text,
            text=True,
            check=True,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
