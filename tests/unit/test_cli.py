from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest

from susanoox import __version__
from susanoox.cli import build_parser, main
from susanoox.config.paths import AppPaths


def test_parser_accepts_supported_model() -> None:
    arguments = build_parser().parse_args(["--model", "susanoox-large"])

    assert arguments.model == "susanoox-large"


def test_runtime_version_uses_installed_package_metadata() -> None:
    assert __version__ == version("susanoox")


def test_parser_accepts_plan_mode() -> None:
    arguments = build_parser().parse_args(["--plan"])

    assert arguments.plan is True


def test_sessions_command_lists_empty_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "logs")

    class TestPaths:
        @classmethod
        def discover(cls) -> AppPaths:
            return paths

    monkeypatch.setattr("susanoox.cli.AppPaths", TestPaths)
    monkeypatch.chdir(tmp_path)

    main(["sessions"])

    assert "No saved sessions" in capsys.readouterr().out
