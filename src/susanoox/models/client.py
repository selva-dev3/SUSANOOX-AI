from __future__ import annotations

import logging
from base64 import b64encode
from collections.abc import AsyncGenerator, Sequence
from typing import cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from susanoox.config.settings import ModelName, Settings
from susanoox.models.catalog import get_model
from susanoox.models.protocol import (
    ConversationMessage,
    StreamEvent,
    TextDelta,
    TokenUsage,
    UsageUpdate,
)
from susanoox.utils.errors import (
    AuthenticationError,
    ContextOverflowError,
    RetryableServiceError,
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
            # Retry ownership belongs to the conversation policy so attempts stay observable.
            max_retries=0,
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
        self,
        messages: Sequence[ConversationMessage],
        *,
        model: ModelName,
    ) -> AsyncGenerator[StreamEvent, None]:
        capability = get_model(model)
        if capability is None or not capability.supports_chat:
            raise ServiceResponseError("Select a supported chat model with /model.")
        if capability.supports_images is False and any(message.images for message in messages):
            raise ServiceResponseError(
                "This model cannot read image context. "
                "Select another model or clear the conversation."
            )
        request_messages = cast(
            list[ChatCompletionMessageParam],
            [self._serialize_message(message) for message in messages],
        )
        _LOGGER.debug(
            "Starting streamed chat request with %d messages using %s",
            len(messages),
            model,
        )
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=request_messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            try:
                async for chunk in stream:
                    if chunk.choices:
                        content = chunk.choices[0].delta.content
                        if content:
                            yield TextDelta(content)
                    if chunk.usage is not None:
                        yield UsageUpdate(
                            TokenUsage(
                                prompt_tokens=chunk.usage.prompt_tokens,
                                completion_tokens=chunk.usage.completion_tokens,
                            )
                        )
            finally:
                await stream.close()
        except openai.AuthenticationError as error:
            raise AuthenticationError(
                "Authentication expired or was rejected. Re-enter your API key."
            ) from error
        except (openai.APIConnectionError, openai.APITimeoutError) as error:
            raise RetryableServiceError(
                "The connection to Susanoox was interrupted. You can retry the message."
            ) from error
        except openai.BadRequestError as error:
            detail = str(error).casefold()
            if "context" in detail and any(
                marker in detail for marker in ("length", "window", "token", "maximum")
            ):
                raise ContextOverflowError(
                    "The conversation exceeded the model context window. Susanoox will compact it."
                ) from error
            raise ServiceResponseError(
                "Susanoox rejected the request. Check the selected model and request content."
            ) from error
        except openai.APIStatusError as error:
            if error.status_code in {408, 409, 429} or error.status_code >= 500:
                raise RetryableServiceError(
                    "Susanoox is temporarily unavailable. The request may be retried."
                ) from error
            raise ServiceResponseError(
                "Susanoox rejected the request. You can revise it and try again."
            ) from error
        except openai.APIError as error:
            raise ServiceResponseError(
                "Susanoox returned an unexpected error. You can retry the message."
            ) from error
        _LOGGER.debug("Streamed chat request completed")

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _serialize_message(message: ConversationMessage) -> dict[str, object]:
        if not message.images:
            return {"role": message.role, "content": message.content}
        parts: list[dict[str, object]] = [{"type": "text", "text": message.content}]
        for image in message.images:
            encoded = b64encode(image.data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.media_type};base64,{encoded}",
                        "detail": "auto",
                    },
                }
            )
        return {"role": message.role, "content": parts}
