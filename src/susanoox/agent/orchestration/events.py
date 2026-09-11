from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Awaitable, Callable

from susanoox.agent.orchestration.models import ProgressEvent

EventSubscriber = Callable[[ProgressEvent], Awaitable[None] | None]
_LOGGER = logging.getLogger(__name__)


class OrchestrationEventBus:
    """Fan out safe progress without allowing observers to break execution."""

    def __init__(self, *, history_limit: int = 200, subscriber_timeout: float = 0.5) -> None:
        if history_limit < 1 or history_limit > 2_000:
            raise ValueError("history_limit must be from 1 to 2,000")
        if subscriber_timeout <= 0 or subscriber_timeout > 5:
            raise ValueError("subscriber_timeout must be greater than 0 and at most 5 seconds")
        self._history: deque[ProgressEvent] = deque(maxlen=history_limit)
        self._subscribers: dict[int, EventSubscriber] = {}
        self._next_id = 0
        self._subscriber_timeout = subscriber_timeout

    @property
    def history(self) -> tuple[ProgressEvent, ...]:
        return tuple(self._history)

    def subscribe(self, subscriber: EventSubscriber) -> Callable[[], None]:
        subscriber_id = self._next_id
        self._next_id += 1
        self._subscribers[subscriber_id] = subscriber

        def unsubscribe() -> None:
            self._subscribers.pop(subscriber_id, None)

        return unsubscribe

    async def publish(self, event: ProgressEvent) -> None:
        self._history.append(event)
        await asyncio.gather(
            *(self._notify(subscriber, event) for subscriber in tuple(self._subscribers.values()))
        )

    async def _notify(self, subscriber: EventSubscriber, event: ProgressEvent) -> None:
        try:
            result = subscriber(event)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=self._subscriber_timeout)
        except TimeoutError:
            _LOGGER.warning("Orchestration observer timed out for %s", event.event_type)
        except asyncio.CancelledError:
            _LOGGER.warning("Orchestration observer cancelled while rendering %s", event.event_type)
        except Exception:
            _LOGGER.exception("Orchestration observer failed for %s", event.event_type)
