from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.orchestration.models import AgentRole
from susanoox.agent.orchestration.routing import ModelRouter, TaskComplexity


def test_model_router_reserves_large_for_complex_code_and_review() -> None:
    router = ModelRouter()

    assert router.select(AgentRole.CONTEXT, TaskComplexity.COMPLEX) == "susanoox-fast"
    assert router.select(AgentRole.CODE, TaskComplexity.COMPLEX) == "susanoox-large"
    assert router.select(AgentRole.CODE, TaskComplexity.LIGHT) == "susanoox-fast"


@pytest.mark.asyncio
async def test_large_model_requests_are_serialized() -> None:
    router = ModelRouter()
    active = 0
    peak = 0

    async def use_model() -> None:
        nonlocal active, peak
        async with router.lease("susanoox-large"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(use_model(), use_model())

    assert peak == 1
