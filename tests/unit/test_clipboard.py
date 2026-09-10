from __future__ import annotations

import subprocess
from typing import Any, NoReturn

import pytest

from susanoox.ui import clipboard


def test_native_clipboard_uses_wayland_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    def fake_which(command: str) -> str | None:
        return f"/usr/bin/{command}" if command == "wl-copy" else None

    monkeypatch.setattr(clipboard.shutil, "which", fake_which)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs["input"]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    assert clipboard.copy_to_system_clipboard("selected response") is True
    assert calls == [(["wl-copy"], "selected response")]


def test_native_clipboard_failure_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard, "_native_clipboard_command", lambda: ["wl-copy"])

    def fail_run(*args: object, **kwargs: object) -> NoReturn:
        raise subprocess.TimeoutExpired("wl-copy", 2)

    monkeypatch.setattr(clipboard.subprocess, "run", fail_run)

    assert clipboard.copy_to_system_clipboard("selected response") is False
