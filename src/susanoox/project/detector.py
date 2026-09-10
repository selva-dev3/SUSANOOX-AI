from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which

_ROOT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "*.sln",
)


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    root: Path
    working_directory: Path
    kind: str
    language: str | None
    package_manager: str | None
    git_repository: bool


def _git_root(path: Path) -> Path | None:
    git = which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - executable and arguments are controlled
            [git, "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    candidate = Path(result.stdout.strip()).resolve()
    return candidate if candidate.is_dir() else None


def _marker_root(path: Path) -> Path | None:
    for directory in (path, *path.parents):
        for marker in _ROOT_MARKERS:
            if any(directory.glob(marker)):
                return directory
    return None


def _classify(root: Path) -> tuple[str, str | None, str | None]:
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "Python", "Python", "uv" if (root / "uv.lock").exists() else "pip"
    if (root / "package.json").exists():
        manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "npm"
        if (root / "yarn.lock").exists():
            manager = "yarn"
        return "Node.js", "TypeScript/JavaScript", manager
    if (root / "Cargo.toml").exists():
        return "Rust", "Rust", "cargo"
    if (root / "go.mod").exists():
        return "Go", "Go", "go"
    return "Generic", None, None


def detect_project(working_directory: Path) -> ProjectInfo:
    working = working_directory.resolve()
    git_root = _git_root(working)
    marker_root = _marker_root(working)
    if git_root is not None and marker_root is not None:
        try:
            marker_root.relative_to(git_root)
        except ValueError:
            root = git_root
        else:
            root = marker_root
    else:
        root = git_root or marker_root or working
    kind, language, package_manager = _classify(root)
    return ProjectInfo(
        root=root,
        working_directory=working,
        kind=kind,
        language=language,
        package_manager=package_manager,
        git_repository=git_root is not None,
    )
