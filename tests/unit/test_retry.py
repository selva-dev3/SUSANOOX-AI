from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from susanoox.agent.retry import CorrectionBudget, RetryPolicy, collect_with_retry
from susanoox.utils.errors import (
    ContextOverflowError,
    ModelOutputError,
    RetryableServiceError,
    ServiceResponseError,
)


async def test_transient_failure_before_output_is_retried() -> None:
    calls = 0

    async def stream() -> AsyncGenerator[str, None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableServiceError("transient")
        yield "ok"

    policy = RetryPolicy(max_attempts=2, base_delay_seconds=0)

    result = [value async for value in collect_with_retry(stream, policy)]

    assert result == [("ok", 1)]
    assert calls == 2


async def test_failure_after_output_is_never_retried() -> None:
    calls = 0

    async def stream() -> AsyncGenerator[str, None]:
        nonlocal calls
        calls += 1
        yield "partial"
        raise RetryableServiceError("interrupted")

    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0)

    with pytest.raises(RetryableServiceError):
        _ = [value async for value in collect_with_retry(stream, policy)]
    assert calls == 1


async def test_non_retryable_failure_is_not_repeated() -> None:
    calls = 0

    async def stream() -> AsyncGenerator[str, None]:
        nonlocal calls
        calls += 1
        raise ServiceResponseError("bad request")
        yield "unreachable"

    with pytest.raises(ServiceResponseError):
        _ = [value async for value in collect_with_retry(stream, RetryPolicy(max_attempts=3))]
    assert calls == 1


def test_correction_budget_detects_no_progress_and_enforces_permissions() -> None:
    budget = CorrectionBudget(max_iterations=3, max_identical_attempts=2)

    assert budget.consume("same")
    assert budget.consume("same")
    assert not budget.consume("same")
    assert not budget.consume("dangerous", risk="dangerous", permission_granted=True)
    assert not budget.consume("sensitive", risk="sensitive")
    assert budget.consume("sensitive", risk="sensitive", permission_granted=True)
    assert not budget.consume("new")


@pytest.mark.parametrize("error", [ContextOverflowError("large"), ModelOutputError("empty")])
def test_zero_retry_budget_disables_every_retry_category(error: Exception) -> None:
    decision = RetryPolicy(max_attempts=0).classify(error)

    assert not decision.retryable
    assert decision.max_attempts == 0
