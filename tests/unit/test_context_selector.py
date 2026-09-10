from __future__ import annotations

from pathlib import Path

import pytest

from susanoox.context.selector import ContextSelector
from susanoox.project.detector import ProjectInfo, detect_project


def _project(root: Path) -> ProjectInfo:
    return ProjectInfo(
        root=root,
        working_directory=root,
        kind="Python",
        language="Python",
        package_manager="pip",
        git_repository=False,
    )


def test_detect_project_uses_nearest_marker(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "src" / "package"
    nested.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    project = detect_project(nested)

    assert project.root == root
    assert project.kind == "Python"


def test_context_ranks_relevant_files_and_excludes_secrets_and_ignored_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "ignored").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def validate_login(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_auth.py").write_text(
        "def test_login_validation(): pass\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (tmp_path / "ignored" / "auth.py").write_text("secret login\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    selector = ContextSelector(_project(tmp_path), max_files=4, max_chars=10_000)

    snapshot = selector.select("fix login auth validation tests")

    paths = [item.path for item in snapshot.files]
    assert "src/auth.py" in paths
    assert "tests/test_auth.py" in paths
    assert ".env" not in paths
    assert "ignored/auth.py" not in paths
    assert snapshot.total_chars <= 10_000
    assert "untrusted reference data" in snapshot.as_system_context()


def test_context_skips_binary_and_large_files(tmp_path: Path) -> None:
    (tmp_path / "auth.bin").write_bytes(b"login\0secret")
    (tmp_path / "auth.py").write_text("x" * 200, encoding="utf-8")
    selector = ContextSelector(_project(tmp_path), max_file_bytes=100)

    snapshot = selector.select("auth login")

    assert snapshot.files == ()


def test_context_does_not_send_unrelated_project_files_for_greeting(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    selector = ContextSelector(_project(tmp_path))

    snapshot = selector.select("hello")

    assert snapshot.files == ()


def test_context_never_follows_symlink_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside-auth.py"
    outside.write_text("API_KEY=sk-forge-abcdefgh login\n", encoding="utf-8")
    try:
        (project / "auth.py").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    snapshot = ContextSelector(_project(project)).select("auth login")

    assert snapshot.files == ()


def test_redaction_never_expands_context_past_budget(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text(
        "password=x\n" * 500,
        encoding="utf-8",
    )
    selector = ContextSelector(_project(tmp_path), max_chars=1_000)

    snapshot = selector.select("auth password")

    assert snapshot.total_chars <= 1_000
    assert all(len(item.excerpt) <= 1_000 for item in snapshot.files)
