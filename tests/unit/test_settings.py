from __future__ import annotations

from pathlib import Path

import pytest

from susanoox.cli import build_parser
from susanoox.config.paths import AppPaths
from susanoox.config.settings import load_settings
from susanoox.utils.errors import ConfigurationError


def test_vision_model_is_available_in_cli_and_settings(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path, tmp_path, tmp_path, tmp_path)
    args = build_parser().parse_args(["--model", "susanoox-vision"])
    assert args.model == "susanoox-vision"
    assert (
        load_settings(project_path=tmp_path, model_override="susanoox-vision", paths=paths).model
        == "susanoox-vision"
    )


def test_cli_model_overrides_project_and_global_configuration(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[susanoox]\nmodel = "susanoox-large"\n', encoding="utf-8"
    )
    project_config = project_dir / ".susanoox"
    project_config.mkdir(parents=True)
    (project_config / "config.toml").write_text(
        '[susanoox]\nmodel = "susanoox-fast"\n', encoding="utf-8"
    )
    paths = AppPaths(config_dir, tmp_path / "data", tmp_path / "cache", tmp_path / "logs")

    settings = load_settings(
        project_path=project_dir,
        model_override="susanoox-large",
        paths=paths,
    )

    assert settings.model == "susanoox-large"
    assert settings.project_path == project_dir.resolve()


def test_embedding_model_is_rejected_for_chat(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path, tmp_path, tmp_path, tmp_path)

    with pytest.raises(ConfigurationError, match="Unsupported chat model"):
        load_settings(
            project_path=tmp_path,
            model_override="susanoox-embed",
            paths=paths,
        )


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_non_finite_timeout_is_rejected(tmp_path: Path, timeout: str) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f"[susanoox]\nrequest_timeout_seconds = {timeout}\n",
        encoding="utf-8",
    )
    paths = AppPaths(config_dir, tmp_path, tmp_path, tmp_path)

    with pytest.raises(ConfigurationError, match="must be positive"):
        load_settings(project_path=tmp_path, paths=paths)
