from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from susanoox.config.settings import Settings
from susanoox.models.client import SusanooxClient
from susanoox.models.protocol import ConversationMessage


class FakeStream:
    def __init__(self, chunks: tuple[object, ...]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[object]:
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.last_stream: FakeStream | None = None

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            chunks = (
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" world"))]),
            )
            self.last_stream = FakeStream(chunks)
            return self.last_stream
        return SimpleNamespace(choices=[])


class FakeOpenAI:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_client_validates_and_streams_with_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenAI()

    def make_client(**_kwargs: object) -> FakeOpenAI:
        return fake

    monkeypatch.setattr("susanoox.models.client.AsyncOpenAI", make_client)
    settings = Settings(model="susanoox-fast", project_path=Path.cwd())
    client = SusanooxClient(api_key="test-key", settings=settings)

    await client.validate_api_key()
    result = "".join(
        [
            part
            async for part in client.stream_chat([ConversationMessage(role="user", content="Hi")])
        ]
    )
    await client.close()

    assert result == "Hello world"
    assert fake.completions.calls[0]["max_tokens"] == 1
    assert fake.completions.calls[1]["stream"] is True
    assert fake.completions.last_stream is not None
    assert fake.completions.last_stream.closed
    assert fake.closed
