from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PermissionCategory(StrEnum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    SHELL = "shell"
    GIT = "git"
    NETWORK = "network"


class PermissionDecision(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"


def _empty_grants() -> set[PermissionCategory]:
    return set()


@dataclass(slots=True)
class PermissionEngine:
    """Session grants never override an explicit denial or project boundaries."""

    _session_grants: set[PermissionCategory] = field(default_factory=_empty_grants)

    def decide(
        self,
        category: PermissionCategory,
        requested: PermissionDecision,
        *,
        within_project: bool = True,
    ) -> bool:
        if not within_project or requested is PermissionDecision.DENY:
            return False
        if requested is PermissionDecision.ALLOW_SESSION:
            self._session_grants.add(category)
        return True

    def is_granted_for_session(self, category: PermissionCategory) -> bool:
        return category in self._session_grants

    def revoke_session_grants(self) -> None:
        self._session_grants.clear()
