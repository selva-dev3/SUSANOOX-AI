from __future__ import annotations

from susanoox.permissions.policy import PermissionCategory, PermissionDecision, PermissionEngine


def test_session_grant_is_scoped_and_revocable() -> None:
    engine = PermissionEngine()

    assert engine.decide(PermissionCategory.FILE_WRITE, PermissionDecision.ALLOW_SESSION)
    assert engine.is_granted_for_session(PermissionCategory.FILE_WRITE)
    assert not engine.is_granted_for_session(PermissionCategory.SHELL)

    engine.revoke_session_grants()
    assert not engine.is_granted_for_session(PermissionCategory.FILE_WRITE)


def test_project_boundary_and_denial_remain_authoritative() -> None:
    engine = PermissionEngine()

    assert not engine.decide(
        PermissionCategory.FILE_READ,
        PermissionDecision.ALLOW_SESSION,
        within_project=False,
    )
    assert not engine.decide(PermissionCategory.SHELL, PermissionDecision.DENY)
    assert not engine.is_granted_for_session(PermissionCategory.FILE_READ)
