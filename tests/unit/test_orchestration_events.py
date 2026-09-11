from __future__ import annotations

import asyncio

import pytest

from susanoox.agent.orchestration.events import OrchestrationEventBus
from susanoox.agent.orchestration.models import ProgressEvent


@pytest.mark.asyncio
async def test_event_bus_bounds_history_and_isolates_observer_failures() -> None:
    received: list[int] = []
    bus = OrchestrationEventBus(history_limit=1, subscriber_timeout=0.01)

    async def blocked(_event: ProgressEvent) -> None:
        await asyncio.Event().wait()

    def working(event: ProgressEvent) -> None:
        received.append(event.sequence)

    bus.subscribe(blocked)
    bus.subscribe(working)
    first = ProgressEvent(run_id="run", sequence=1, event_type="task", message="started")
    second = first.model_copy(update={"sequence": 2, "message": "completed"})

    await bus.publish(first)
    await bus.publish(second)

    assert received == [1, 2]
    assert bus.history == (second,)
