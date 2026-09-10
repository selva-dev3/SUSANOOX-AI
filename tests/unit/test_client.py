from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from susanoox.config.settings import Settings
from susanoox.models.catalog import MODELS
from susanoox.models.client import SusanooxClient
from susanoox.models.protocol import ConversationMessage, ImageAttachment, TextDelta, UsageUpdate
from susanoox.utils.errors import ServiceResponseError


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
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))], usage=None
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=None))], usage=None
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=" world"))], usage=None
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
                ),
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
    events = [
        event
        async for event in client.stream_chat(
            [ConversationMessage(role="user", content="Hi")],
            model="susanoox-large",
        )
    ]
    await client.close()

    assert (
        "".join(event.content for event in events if isinstance(event, TextDelta)) == "Hello world"
    )
    usage = next(event.usage for event in events if isinstance(event, UsageUpdate))
    assert usage.total_tokens == 6
    assert fake.completions.calls[0]["max_tokens"] == 1
    assert fake.completions.calls[1]["stream"] is True
    assert fake.completions.calls[1]["model"] == "susanoox-large"
    assert fake.completions.calls[1]["stream_options"] == {"include_usage": True}
    assert fake.completions.last_stream is not None
    assert fake.completions.last_stream.closed
    assert fake.closed


async def test_client_serializes_image_as_openai_compatible_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenAI()

    def make_client(**_kwargs: object) -> FakeOpenAI:
        return fake

    monkeypatch.setattr("susanoox.models.client.AsyncOpenAI", make_client)
    client = SusanooxClient(api_key="test-key", settings=Settings(project_path=Path.cwd()))
    attachment = ImageAttachment(
        filename="screen.png",
        media_type="image/png",
        data=b"png-data",
    )

    _ = [
        event
        async for event in client.stream_chat(
            [ConversationMessage(role="user", content="Read this", images=(attachment,))],
            model="susanoox-fast",
        )
    ]

    messages = cast(list[dict[str, object]], fake.completions.calls[0]["messages"])
    content = cast(list[dict[str, object]], messages[0]["content"])
    image_data = cast(dict[str, str], content[1]["image_url"])
    image_url = image_data["url"]
    assert image_url == "data:image/png;base64,cG5nLWRhdGE="


async def test_known_nonvision_model_rejects_image_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOpenAI()

    def make_client(**_kwargs: object) -> FakeOpenAI:
        return fake

    monkeypatch.setattr("susanoox.models.client.AsyncOpenAI", make_client)
    monkeypatch.setattr(
        "susanoox.models.catalog.MODELS", (replace(MODELS[0], supports_images=False),)
    )
    client = SusanooxClient(api_key="test-key", settings=Settings())
    message = ConversationMessage(
        "user", "Read", (ImageAttachment("image.png", "image/png", b"image"),)
    )
    with pytest.raises(ServiceResponseError, match="cannot read image"):
        _ = [event async for event in client.stream_chat([message], model="susanoox-fast")]
    assert fake.completions.calls == []
    await client.close()
