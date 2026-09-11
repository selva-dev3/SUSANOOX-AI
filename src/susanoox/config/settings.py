from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from math import isfinite
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from susanoox.config.paths import AppPaths
from susanoox.utils.errors import ConfigurationError

ModelName: TypeAlias = Literal[
    "susanoox-fast", "susanoox-large", "susanoox-vision", "susanoox-embed"
]
CHAT_MODELS: Final[tuple[ModelName, ...]] = ("susanoox-fast", "susanoox-large", "susanoox-vision")
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
    plan_mode: bool = False
    auto_context: bool = False
    context_max_files: int = 12
    context_max_chars: int = 40_000
    context_max_file_bytes: int = 1_000_000
    summary_trigger_chars: int = 48_000
    summary_recent_messages: int = 8
    api_retry_attempts: int = 2
    retry_base_delay_seconds: float = 0.5
    agent_max_parallel_tasks: int = 2
    agent_max_subagents: int = 2
    agent_max_background_tasks: int = 2
    agent_max_retries: int = 2


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
    validators: tuple[tuple[str, int, int], ...] = (
        ("context_max_files", 1, 40),
        ("context_max_chars", 1_000, 120_000),
        ("context_max_file_bytes", 1_024, 5_000_000),
        ("summary_trigger_chars", 4_000, 500_000),
        ("summary_recent_messages", 2, 30),
        ("api_retry_attempts", 0, 5),
        ("agent_max_parallel_tasks", 1, 8),
        ("agent_max_subagents", 1, 4),
        ("agent_max_background_tasks", 1, 4),
        ("agent_max_retries", 0, 5),
    )
    updates: dict[str, object] = {}
    for name, minimum, maximum in validators:
        value = app.get(name)
        if value is None:
            continue
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
        ):
            raise ConfigurationError(
                f"{name} in {path} must be an integer from {minimum} to {maximum}."
            )
        updates[name] = value
    for name in ("plan_mode", "auto_context"):
        value = app.get(name)
        if value is not None:
            if not isinstance(value, bool):
                raise ConfigurationError(f"{name} in {path} must be true or false.")
            updates[name] = value
    retry_delay = app.get("retry_base_delay_seconds")
    if retry_delay is not None:
        if (
            not isinstance(retry_delay, (int, float))
            or isinstance(retry_delay, bool)
            or not isfinite(retry_delay)
            or retry_delay < 0
            or retry_delay > 30
        ):
            raise ConfigurationError(
                f"retry_base_delay_seconds in {path} must be from 0 to 30 seconds."
            )
        updates["retry_base_delay_seconds"] = float(retry_delay)
    if updates:
        values = {item.name: getattr(updated, item.name) for item in fields(updated)}
        values.update(updates)
        updated = Settings(**values)  # pyright: ignore[reportArgumentType]
    return updated


def load_settings(
    *,
    project_path: Path,
    model_override: str | None = None,
    debug: bool = False,
    plan_override: bool | None = None,
    auto_context_override: bool | None = None,
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
    if plan_override is not None:
        settings = replace(settings, plan_mode=plan_override)
    if auto_context_override is not None:
        settings = replace(settings, auto_context=auto_context_override)
    return settings
