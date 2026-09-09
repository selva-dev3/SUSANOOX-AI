from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence
from typing import cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from susanoox.config.settings import Settings
from susanoox.models.protocol import ConversationMessage
from susanoox.utils.errors import (
    AuthenticationError,
    ServiceConnectionError,
    ServiceResponseError,
)

_VALIDATION_PROMPT = "Reply with OK."
_LOGGER = logging.getLogger(__name__)


class SusanooxClient:
    """Typed adapter around the OpenAI-compatible Susanoox API."""

    def __init__(self, *, api_key: str, settings: Settings) -> None:
        self._model = settings.model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            max_retries=2,
        )

    async def validate_api_key(self) -> None:
        _LOGGER.debug("Starting API credential validation for model %s", self._model)
        try:
            await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": _VALIDATION_PROMPT}],
                max_tokens=1,
            )
        except openai.AuthenticationError as error:
            _LOGGER.info("API credential validation was rejected")
            raise AuthenticationError(
                "The supplied API key is invalid or unavailable. Please enter a valid API key."
            ) from error
        except (openai.APIConnectionError, openai.APITimeoutError) as error:
            _LOGGER.info("API credential validation could not reach the service")
            raise ServiceConnectionError(
                "Susanoox could not be reached. Check your connection and try again."
            ) from error
        except openai.APIError as error:
            _LOGGER.info("API credential validation received a service error")
            raise ServiceResponseError(
                "Susanoox could not verify the key right now. Please try again shortly."
            ) from error
        _LOGGER.debug("API credential validation completed")

    async def stream_chat(
        self, messages: Sequence[ConversationMessage]
    ) -> AsyncGenerator[str, None]:
        request_messages = cast(
            list[ChatCompletionMessageParam],
            [{"role": message.role, "content": message.content} for message in messages],
        )
        _LOGGER.debug("Starting streamed chat request with %d messages", len(messages))
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=request_messages,
                stream=True,
            )
            try:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
            finally:
                await stream.close()
        except openai.AuthenticationError as error:
            raise AuthenticationError(
                "Authentication expired or was rejected. Re-enter your API key."
            ) from error
        except (openai.APIConnectionError, openai.APITimeoutError) as error:
            raise ServiceConnectionError(
                "The connection to Susanoox was interrupted. You can retry the message."
            ) from error
        except openai.APIError as error:
            raise ServiceResponseError(
                "Susanoox returned an unexpected error. You can retry the message."
            ) from error
        _LOGGER.debug("Streamed chat request completed")

    async def close(self) -> None:
        await self._client.close()
