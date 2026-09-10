from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, TypeVar

from susanoox.utils.errors import ContextOverflowError, ModelOutputError, RetryableServiceError

_T = TypeVar("_T")
ActionRisk = Literal["safe", "normal", "sensitive", "dangerous"]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retryable: bool
    category: str
    max_attempts: int


class RetryPolicy:
    """Own bounded retries so transport and agent retries cannot multiply invisibly."""

    def __init__(self, *, max_attempts: int = 2, base_delay_seconds: float = 0.5) -> None:
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    def classify(self, error: Exception) -> RetryDecision:
        if isinstance(error, ContextOverflowError):
            attempts = min(1, self.max_attempts)
            return RetryDecision(attempts > 0, "context_overflow", attempts)
        if isinstance(error, ModelOutputError):
            attempts = min(1, self.max_attempts)
            return RetryDecision(attempts > 0, "empty_model_output", attempts)
        if isinstance(error, RetryableServiceError):
            return RetryDecision(True, "service_transient", self.max_attempts)
        return RetryDecision(False, "non_retryable", 0)

    def delay(self, retry_number: int) -> float:
        return self.base_delay_seconds * (2 ** max(0, retry_number - 1))

    @staticmethod
    def fingerprint(action: str, failure_category: str, workspace_revision: str = "") -> str:
        value = "\0".join((action, failure_category, workspace_revision))
        return sha256(value.encode("utf-8", errors="replace")).hexdigest()

    async def backoff(self, retry_number: int) -> None:
        await asyncio.sleep(self.delay(retry_number))


class CorrectionBudget:
    """Stops repeated agent actions and keeps sensitive permissions authoritative."""

    def __init__(self, *, max_iterations: int = 20, max_identical_attempts: int = 2) -> None:
        self.max_iterations = max_iterations
        self.max_identical_attempts = max_identical_attempts
        self.iterations = 0
        self._attempts: dict[str, int] = {}

    def consume(
        self,
        fingerprint: str,
        *,
        risk: ActionRisk = "normal",
        permission_granted: bool = False,
    ) -> bool:
        if risk == "dangerous":
            return False
        if risk == "sensitive" and not permission_granted:
            return False
        previous = self._attempts.get(fingerprint, 0)
        if self.iterations >= self.max_iterations or previous >= self.max_identical_attempts:
            return False
        self.iterations += 1
        self._attempts[fingerprint] = previous + 1
        return True


async def collect_with_retry(
    create_stream: Callable[[], AsyncGenerator[_T, None]],
    policy: RetryPolicy,
    before_retry: Callable[[Exception, int], Awaitable[None]] | None = None,
    is_visible: Callable[[_T], bool] | None = None,
) -> AsyncGenerator[tuple[_T, int], None]:
    """Retry only failures occurring before any output has been exposed."""
    retry_number = 0
    while True:
        emitted = False
        try:
            attempt_stream = create_stream()
            async with aclosing(attempt_stream):
                async for delta in attempt_stream:
                    emitted = emitted or is_visible is None or is_visible(delta)
                    yield delta, retry_number
            return
        except Exception as error:
            decision = policy.classify(error)
            if emitted or not decision.retryable or retry_number >= decision.max_attempts:
                raise
            retry_number += 1
            if before_retry is not None:
                await before_retry(error, retry_number)
            await policy.backoff(retry_number)
