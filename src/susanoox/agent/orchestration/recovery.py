from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256

from susanoox.utils.errors import RetryableServiceError, SusanooxError


class RetryableTaskError(SusanooxError):
    def __init__(self, message: str, *, category: str = "transient") -> None:
        super().__init__(message)
        self.category = category


class PermissionDeniedTaskError(SusanooxError):
    """A task stopped because centralized permission was denied."""


class UnsafeTaskError(SusanooxError):
    """A task requested an operation that policy must never retry."""


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    category: str
    retryable: bool
    safe_message: str


@dataclass(slots=True)
class RecoveryPolicy:
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def classify(self, error: Exception) -> RecoveryDecision:
        if isinstance(error, PermissionDeniedTaskError):
            return RecoveryDecision("permission_denied", False, "Permission was denied.")
        if isinstance(error, UnsafeTaskError):
            return RecoveryDecision("unsafe", False, "The requested operation is unsafe.")
        if isinstance(error, RetryableTaskError):
            return RecoveryDecision(error.category, True, str(error)[:500])
        if isinstance(error, (RetryableServiceError, TimeoutError, asyncio.TimeoutError)):
            return RecoveryDecision("transient", True, "A temporary operation failure occurred.")
        return RecoveryDecision("fatal", False, "The task failed and cannot be retried safely.")

    @staticmethod
    def fingerprint(task_id: str, category: str, operation_signature: str = "") -> str:
        value = "\0".join((task_id, category, operation_signature))
        return sha256(value.encode("utf-8", errors="replace")).hexdigest()

    def delay(self, attempt: int) -> float:
        return min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(0, attempt - 1)),
        )
