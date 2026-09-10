from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable

from susanoox.agent.types import AgentEvent

ActivitySubscriber = Callable[[AgentEvent], None]
_LOGGER = logging.getLogger(__name__)


class CancellationToken:
    """Cooperative cancellation shared by model, search, and tool operations."""

    def __init__(self) -> None:
        self._cancelled = asyncio.Event()
        self._reason = "Operation cancelled"

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "Operation cancelled") -> None:
        if self._cancelled.is_set():
            return
        normalized = " ".join(reason.split())[:500]
        self._reason = normalized or "Operation cancelled"
        self._cancelled.set()

    async def wait(self) -> None:
        await self._cancelled.wait()

    def checkpoint(self) -> None:
        if self.is_cancelled:
            raise asyncio.CancelledError(self._reason)


class ActivityPublisher:
    """Publish safe task events without coupling producers to Textual widgets."""

    def __init__(self, *, history_limit: int = 100) -> None:
        if history_limit < 1 or history_limit > 1_000:
            raise ValueError("history_limit must be from 1 to 1,000")
        self._history: deque[AgentEvent] = deque(maxlen=history_limit)
        self._subscribers: dict[int, ActivitySubscriber] = {}
        self._next_subscriber_id = 0

    @property
    def history(self) -> tuple[AgentEvent, ...]:
        return tuple(self._history)

    def subscribe(self, subscriber: ActivitySubscriber) -> Callable[[], None]:
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        self._subscribers[subscriber_id] = subscriber

        def unsubscribe() -> None:
            self._subscribers.pop(subscriber_id, None)

        return unsubscribe

    def publish(self, event: AgentEvent) -> None:
        self._history.append(event)
        for subscriber in tuple(self._subscribers.values()):
            try:
                subscriber(event)
            except asyncio.CancelledError:
                # Subscriber cancellation belongs to the renderer, not the task being observed.
                _LOGGER.warning("Activity subscriber was cancelled while rendering %s", event.kind)
            except Exception:
                # An activity renderer must never terminate the task it observes.
                _LOGGER.exception("Activity subscriber failed while rendering %s", event.kind)
