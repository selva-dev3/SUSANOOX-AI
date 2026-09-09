from __future__ import annotations

import asyncio

import pytest

from susanoox.ui.streaming import StreamRenderer, cancelled_content


async def test_fast_stream_uses_a_single_serialized_final_render() -> None:
    rendered: list[str] = []

    async def render(content: str) -> None:
        rendered.append(content)

    renderer = StreamRenderer(interval_seconds=0.05, clock=lambda: 0.0)
    for _ in range(1_000):
        await renderer.add("x", render)
    await renderer.finish(render)

    assert rendered == ["x", "x" * 1_000]


async def test_stream_renders_at_the_configured_cadence() -> None:
    rendered: list[str] = []
    times = iter((0.0, 0.01, 0.01, 0.02, 0.07, 0.07))

    async def render(content: str) -> None:
        rendered.append(content)

    renderer = StreamRenderer(interval_seconds=0.05, clock=lambda: next(times))
    await renderer.add("a", render)
    await renderer.add("b", render)
    await renderer.add("c", render)
    await renderer.finish(render)

    assert rendered == ["a", "abc"]


async def test_pending_content_flushes_when_the_stream_pauses() -> None:
    rendered: list[str] = []

    async def render(content: str) -> None:
        rendered.append(content)

    renderer = StreamRenderer(interval_seconds=0.01)
    await renderer.add("first", render)
    await renderer.add(" second", render)
    await asyncio.sleep(0.02)
    await renderer.close()

    assert rendered == ["first", "first second"]


async def test_failed_background_flush_is_raised_by_the_next_delta() -> None:
    flush_failed = asyncio.Event()
    render_count = 0

    async def render(_content: str) -> None:
        nonlocal render_count
        render_count += 1
        if render_count == 2:
            flush_failed.set()
            raise ValueError("render failed")

    renderer = StreamRenderer(interval_seconds=0.01)
    await renderer.add("first", render)
    await renderer.add(" second", render)
    await asyncio.wait_for(flush_failed.wait(), timeout=1)
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="render failed"):
        await renderer.add(" third", render)


def test_cancelled_partial_content_is_clearly_marked() -> None:
    rendered = cancelled_content("partial response")

    assert rendered.startswith("partial response")
    assert "cancelled and excluded from context" in rendered
