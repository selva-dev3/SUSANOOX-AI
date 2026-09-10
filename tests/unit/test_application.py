from __future__ import annotations

from pathlib import Path

import pytest

from susanoox.app.application import run_application
from susanoox.config.paths import AppPaths
from susanoox.config.settings import Settings
from susanoox.sessions.storage import SessionStore
from susanoox.utils.errors import SessionError


class FakeApp:
    settings: Settings | None = None
    session_id: str | None = None

    def __init__(self, **values: object) -> None:
        FakeApp.settings = values["settings"]  # type: ignore[assignment]
        FakeApp.session_id = values["session_id"]  # type: ignore[assignment]

    def run(self) -> None:
        return


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AppPaths:
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "logs")
    monkeypatch.setattr("susanoox.app.application.AppPaths.discover", lambda: paths)
    monkeypatch.setattr("susanoox.app.application.SusanooxApp", FakeApp)
    return paths


def test_resume_restores_saved_model_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _patch_runtime(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    store = SessionStore(paths.data_dir / "sessions.sqlite3")
    store.initialize()
    session = store.create(project_root=project, model="susanoox-large")

    run_application(Settings(project_path=project), resume_session_id=session.id)

    assert FakeApp.settings is not None
    assert FakeApp.settings.model == "susanoox-large"
    assert FakeApp.session_id == session.id


def test_resume_rejects_session_from_another_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _patch_runtime(monkeypatch, tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    store = SessionStore(paths.data_dir / "sessions.sqlite3")
    store.initialize()
    session = store.create(project_root=first, model="susanoox-fast")

    with pytest.raises(SessionError, match="different project"):
        run_application(Settings(project_path=second), resume_session_id=session.id)
