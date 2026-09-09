from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from susanoox.config.paths import AppPaths
from susanoox.utils.errors import ConfigurationError

ModelName: TypeAlias = Literal["susanoox-fast", "susanoox-large", "susanoox-embed"]
CHAT_MODELS: Final[tuple[ModelName, ...]] = ("susanoox-fast", "susanoox-large")
ALL_MODELS: Final[tuple[ModelName, ...]] = (*CHAT_MODELS, "susanoox-embed")
DEFAULT_MODEL: Final[ModelName] = "susanoox-fast"
DEFAULT_BASE_URL: Final = "https://llm.herd.casa/v1"


@dataclass(frozen=True, slots=True)
class Settings:
    model: ModelName = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    request_timeout_seconds: float = 60.0
    project_path: Path = field(default_factory=Path.cwd)
    debug: bool = False


def _read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"Unable to read configuration at {path}: {error}") from error


def _apply_file(settings: Settings, path: Path) -> Settings:
    raw = _read_toml(path)
    app_value = raw.get("susanoox", raw)
    if not isinstance(app_value, dict):
        raise ConfigurationError(f"Configuration at {path} must contain a table.")
    app = cast(dict[str, object], app_value)

    model = app.get("model")
    timeout = app.get("request_timeout_seconds")
    updated = settings
    if model is not None:
        if not isinstance(model, str) or model not in CHAT_MODELS:
            raise ConfigurationError(f"Unsupported chat model in {path}: {model!r}")
        updated = replace(updated, model=cast(ModelName, model))
    if timeout is not None:
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise ConfigurationError(f"request_timeout_seconds in {path} must be positive.")
        updated = replace(updated, request_timeout_seconds=float(timeout))
    return updated


def load_settings(
    *,
    project_path: Path,
    model_override: str | None = None,
    debug: bool = False,
    paths: AppPaths | None = None,
) -> Settings:
    """Load global then project preferences, followed by explicit CLI overrides."""
    resolved_project = project_path.resolve()
    app_paths = paths or AppPaths.discover()
    settings = Settings(project_path=resolved_project, debug=debug)
    settings = _apply_file(settings, app_paths.config_dir / "config.toml")
    settings = _apply_file(settings, resolved_project / ".susanoox" / "config.toml")
    if model_override is not None:
        if model_override not in CHAT_MODELS:
            models = ", ".join(CHAT_MODELS)
            raise ConfigurationError(
                f"Unsupported chat model {model_override!r}. Choose: {models}."
            )
        settings = replace(settings, model=cast(ModelName, model_override))
    return settings
