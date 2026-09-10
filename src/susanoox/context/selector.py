from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from shutil import which
from time import monotonic

from susanoox.context.models import ContextFile, ContextSnapshot
from susanoox.project.detector import ProjectInfo
from susanoox.security.redaction import redact_secrets

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{2,}")
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
    }
)
_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx"})
_CONFIG_NAMES = frozenset(
    {"pyproject.toml", "package.json", "go.mod", "Cargo.toml", "README.md", "AGENTS.md"}
)
_CACHE_TTL_SECONDS = 5.0
_STOP_WORDS = frozenset(
    {
        "add",
        "and",
        "can",
        "change",
        "code",
        "create",
        "file",
        "fix",
        "for",
        "from",
        "how",
        "implement",
        "into",
        "please",
        "that",
        "the",
        "this",
        "with",
    }
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    relative: str
    score: float
    reasons: tuple[str, ...]


class ContextSelector:
    def __init__(
        self,
        project: ProjectInfo,
        *,
        max_files: int = 12,
        max_chars: int = 40_000,
        max_file_bytes: int = 1_000_000,
    ) -> None:
        self.project = project
        self.max_files = max_files
        self.max_chars = max_chars
        self.max_file_bytes = max_file_bytes
        self._paths: tuple[Path, ...] | None = None
        self._paths_cached_at = 0.0
        self._match_cache: dict[frozenset[str], tuple[float, frozenset[str]]] = {}

    def select(self, query: str) -> ContextSnapshot:
        terms = self._query_terms(query)
        content_matches = self._content_matches(terms)
        changed = self._changed_paths()
        candidates = sorted(
            (
                candidate
                for path in self._discover()
                if (candidate := self._score(path, terms, content_matches, changed))
            ),
            key=lambda item: (-item.score, item.relative.casefold()),
        )
        selected: list[ContextFile] = []
        remaining = self.max_chars
        for candidate in candidates[: self.max_files * 3]:
            if len(selected) >= self.max_files or remaining <= 0:
                break
            excerpt, truncated = self._read_excerpt(candidate.path, remaining)
            if excerpt is None:
                continue
            selected.append(
                ContextFile(
                    path=self._display_path(candidate.relative),
                    score=candidate.score,
                    reasons=candidate.reasons,
                    excerpt=excerpt,
                    truncated=truncated,
                )
            )
            remaining -= len(excerpt)
        return ContextSnapshot(
            query=query[:20_000],
            project_root=str(self.project.root),
            files=tuple(selected),
            omitted_files=max(0, len(candidates) - len(selected)),
            total_chars=sum(len(item.excerpt) for item in selected),
        )

    @staticmethod
    def _query_terms(query: str) -> set[str]:
        terms: set[str] = set()
        for match in _WORD.finditer(query[:20_000]):
            normalized = match.group(0).casefold()[:64]
            if normalized not in _STOP_WORDS:
                terms.add(normalized)
            if len(terms) >= 32:
                break
        return terms

    @staticmethod
    def _display_path(value: str) -> str:
        cleaned = "".join(character if character.isprintable() else "?" for character in value)
        return cleaned.replace("`", "'")[:500]

    def _discover(self) -> tuple[Path, ...]:
        now = monotonic()
        if self._paths is not None and now - self._paths_cached_at < _CACHE_TTL_SECONDS:
            return self._paths
        root = self.project.root
        relative_paths: list[str] = []
        if self.project.git_repository:
            git = which("git")
            try:
                if git is None:
                    raise OSError("git is unavailable")
                result = subprocess.run(  # noqa: S603 - executable and arguments are controlled
                    [
                        git,
                        "-C",
                        str(root),
                        "ls-files",
                        "--cached",
                        "--others",
                        "--exclude-standard",
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    relative_paths = result.stdout.splitlines()
            except (OSError, subprocess.SubprocessError):
                pass
        if not relative_paths:
            for directory, names, filenames in os.walk(root, followlinks=False):
                names[:] = [
                    name
                    for name in names
                    if name not in _EXCLUDED_PARTS and not (Path(directory) / name).is_symlink()
                ]
                for filename in filenames:
                    path = Path(directory) / filename
                    try:
                        relative = path.relative_to(root)
                    except ValueError:
                        continue
                    if not self._ignored_without_git(relative):
                        relative_paths.append(str(relative))
        safe: list[Path] = []
        for relative in relative_paths:
            path = root / relative
            parts = Path(relative).parts
            if _EXCLUDED_PARTS.intersection(parts) or self._is_sensitive(path) or path.is_symlink():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                safe.append(resolved)
        self._paths = tuple(safe)
        self._paths_cached_at = now
        return self._paths

    @staticmethod
    def _is_sensitive(path: Path) -> bool:
        name = path.name.casefold()
        return (
            name in _SENSITIVE_NAMES
            or name.startswith(".env.")
            or name in {"secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml"}
            or path.suffix.casefold() in _SENSITIVE_SUFFIXES
        )

    def _ignored_without_git(self, relative: Path) -> bool:
        ignore_file = self.project.root / ".gitignore"
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return False
        value = relative.as_posix()
        ignored = False
        for raw in lines:
            pattern = raw.strip()
            if not pattern or pattern.startswith("#"):
                continue
            negated = pattern.startswith("!")
            if negated:
                pattern = pattern[1:]
            pattern = pattern.lstrip("/")
            directory_pattern = pattern.rstrip("/")
            matches = (
                fnmatch(value, pattern)
                or fnmatch(value, f"{directory_pattern}/**")
                or ("/" not in pattern and any(fnmatch(part, pattern) for part in relative.parts))
            )
            if matches:
                ignored = not negated
        return ignored

    def _score(
        self,
        path: Path,
        terms: set[str],
        content_matches: frozenset[str],
        changed: frozenset[str],
    ) -> _Candidate | None:
        try:
            relative = path.relative_to(self.project.root).as_posix()
            size = path.stat().st_size
        except (OSError, ValueError):
            return None
        if size > self.max_file_bytes or size == 0:
            return None
        relative_terms = {word.casefold() for word in _WORD.findall(relative)}
        overlap = terms.intersection(relative_terms)
        reasons: list[str] = []
        score = float(len(overlap) * 8)
        if overlap:
            reasons.append("path matches: " + ", ".join(sorted(overlap)))
        content_match = relative in content_matches
        config_relevant = bool(
            terms.intersection(
                {"build", "configuration", "dependencies", "install", "package", "project", "test"}
            )
        )
        if path.name in _CONFIG_NAMES and (overlap or content_match or config_relevant):
            score += 2
            reasons.append("project configuration/documentation")
        if content_match:
            score += 5
            reasons.append("content matches task terms")
        if relative in changed:
            score += 3
            reasons.append("recent Git change")
        query_mentions_tests = bool({"test", "tests", "testing"}.intersection(terms))
        is_test = "test" in path.name.casefold() or "tests" in relative_terms
        if query_mentions_tests and is_test:
            score += 5
            reasons.append("test relationship")
        if not overlap and not reasons:
            return None
        return _Candidate(path, relative, score, tuple(reasons))

    def _content_matches(self, terms: set[str]) -> frozenset[str]:
        key = frozenset(terms)
        cached = self._match_cache.get(key)
        now = monotonic()
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        rg = which("rg")
        if not terms:
            return frozenset()
        if rg is None:
            fallback_matches: set[str] = set()
            for path in self._discover()[:500]:
                try:
                    text = path.read_bytes()[:16_000].decode("utf-8", errors="ignore").casefold()
                    relative = path.relative_to(self.project.root).as_posix()
                except (OSError, ValueError):
                    continue
                if any(term in text for term in terms):
                    fallback_matches.add(relative)
            return frozenset(fallback_matches)
        pattern = "|".join(re.escape(term) for term in sorted(terms))
        command = [
            rg,
            "--files-with-matches",
            "--ignore-case",
            "--max-filesize",
            str(self.max_file_bytes),
            "--glob",
            "!*.lock",
        ]
        for part in sorted(_EXCLUDED_PARTS):
            command.extend(("--glob", f"!{part}/**"))
        command.extend((pattern, "."))
        try:
            result = subprocess.run(  # noqa: S603 - executable and arguments are controlled
                command,
                cwd=self.project.root,
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return frozenset()
        matches = frozenset(line.removeprefix("./") for line in result.stdout.splitlines())
        if len(self._match_cache) >= 32:
            self._match_cache.pop(next(iter(self._match_cache)))
        self._match_cache[key] = (now, matches)
        return matches

    def _changed_paths(self) -> frozenset[str]:
        git = which("git")
        if git is None or not self.project.git_repository:
            return frozenset()
        try:
            prefix_result = subprocess.run(  # noqa: S603 - executable and arguments are controlled
                [git, "-C", str(self.project.root), "rev-parse", "--show-prefix"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
            result = subprocess.run(  # noqa: S603 - executable and arguments are controlled
                [
                    git,
                    "-C",
                    str(self.project.root),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return frozenset()
        prefix = prefix_result.stdout.strip()
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            value = line[3:].strip()
            if " -> " in value:
                value = value.rpartition(" -> ")[2]
            if prefix:
                if not value.startswith(prefix):
                    continue
                value = value.removeprefix(prefix)
            if value:
                paths.add(value)
        return frozenset(paths)

    def _read_excerpt(self, path: Path, budget: int) -> tuple[str | None, bool]:
        limit = min(budget, 8_000)
        try:
            raw = path.read_bytes()[: limit + 1]
        except OSError:
            return None, False
        if b"\0" in raw:
            return None, False
        redacted = redact_secrets(raw[:limit].decode("utf-8", errors="replace"))
        text = redacted[:limit]
        return text, len(raw) > limit or len(redacted) > limit
