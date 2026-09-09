from __future__ import annotations

from importlib.metadata import version

import pytest

from susanoox import __version__
from susanoox.cli import build_parser, main


def test_parser_accepts_supported_model() -> None:
    arguments = build_parser().parse_args(["--model", "susanoox-large"])

    assert arguments.model == "susanoox-large"


def test_runtime_version_uses_installed_package_metadata() -> None:
    assert __version__ == version("susanoox")


def test_sessions_command_fails_explicitly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["sessions"])

    assert exit_info.value.code == 2
    assert "will be available" in capsys.readouterr().err
