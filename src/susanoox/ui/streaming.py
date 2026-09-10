from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from time import monotonic

RenderCallback = Callable[[str], Awaitable[None]]
Clock = Callable[[], float]


def cancelled_content(partial_content: str) -> str:
    marker = "_Response cancelled and excluded from context._"
    return f"{partial_content}\n\n---\n{marker}" if partial_content else marker


class StreamRenderer:
    """Accumulate stream deltas and serialize renders at a bounded cadence."""

    def __init__(self, *, interval_seconds: float, clock: Clock = monotonic) -> None:
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._last_rendered_at = clock()
        self._last_rendered_content = ""
        self._pending_flush: asyncio.Task[None] | None = None
        self._flush_rendering = False
        self._render_lock = asyncio.Lock()
        self.content = ""

    async def add(self, delta: str, render: RenderCallback) -> bool:
        await self._raise_completed_flush()
        if self._flush_rendering:
            await self._cancel_pending_flush()
        self.content += delta
        now = self._clock()
        if not self._last_rendered_content:
            await self._render(render)
            return True
        elapsed = now - self._last_rendered_at
        if elapsed >= self._interval_seconds:
            await self._cancel_pending_flush()
            await self._render(render)
            return True
        if self._pending_flush is not None and self._pending_flush.done():
            await self._raise_completed_flush()
        if self._pending_flush is None:
            delay = self._interval_seconds - elapsed
            self._pending_flush = asyncio.create_task(self._flush_after(delay, render))
        return False

    async def _raise_completed_flush(self) -> None:
        pending = self._pending_flush
        if pending is None or not pending.done():
            return
        self._pending_flush = None
        await pending

    async def finish(self, render: RenderCallback) -> None:
        await self._cancel_pending_flush()
        await self._render(render)

    async def close(self) -> Exception | None:
        """Cancel and drain pending work without replacing an active error."""
        pending = self._pending_flush
        self._pending_flush = None
        if pending is None:
            return None
        if not pending.done():
            pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            return None
        except Exception as error:
            return error
        return None

    async def _flush_after(self, delay: float, render: RenderCallback) -> None:
        await asyncio.sleep(delay)
        self._flush_rendering = True
        try:
            await self._render(render)
        finally:
            self._flush_rendering = False

    async def _render(self, render: RenderCallback) -> None:
        async with self._render_lock:
            if self.content == self._last_rendered_content:
                return
            snapshot = self.content
            await render(snapshot)
            self._last_rendered_content = snapshot
            self._last_rendered_at = self._clock()

    async def _cancel_pending_flush(self) -> None:
        pending = self._pending_flush
        self._pending_flush = None
        if pending is None:
            return
        if pending.done():
            with suppress(asyncio.CancelledError):
                await pending
            return
        if not self._flush_rendering:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        else:
            await pending
