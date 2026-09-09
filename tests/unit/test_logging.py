from __future__ import annotations

import os
from pathlib import Path
from stat import S_IMODE

import pytest

from susanoox.utils.logging import configure_logging


def test_logging_disables_itself_when_directory_is_unwritable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_mkdir(*_args: object, **_kwargs: object) -> None:
        raise OSError("read only")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert configure_logging(tmp_path / "susanoox.log") is False


@pytest.mark.skipif(os.name == "nt", reason="Windows secures the user profile with ACLs")
def test_posix_log_file_uses_owner_only_permissions(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "susanoox.log"

    assert configure_logging(log_path, debug=True) is True
    assert S_IMODE(log_path.stat().st_mode) == 0o600
    assert "Redacted debug logging enabled" in log_path.read_text(encoding="utf-8")
