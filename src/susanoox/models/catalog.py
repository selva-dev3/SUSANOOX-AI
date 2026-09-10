from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from susanoox.config.settings import ModelName


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: ModelName
    description: str
    supports_chat: bool
    # None means the deployment's vision capability has not been verified.
    supports_images: bool | None


MODELS: Final[tuple[ModelInfo, ...]] = (
    ModelInfo(
        name="susanoox-fast",
        description="Quick tasks, tool calling, and frequent requests",
        supports_chat=True,
        supports_images=False,
    ),
    ModelInfo(
        name="susanoox-large",
        description="Complex reasoning, coding, and hard questions",
        supports_chat=True,
        supports_images=False,
    ),
    ModelInfo(
        name="susanoox-vision",
        description="Images, screenshots, diagrams and OCR · initial warm-up 10-20s",
        supports_chat=True,
        supports_images=True,
    ),
    ModelInfo(
        name="susanoox-embed",
        description="Embeddings for search and retrieval",
        supports_chat=False,
        supports_images=False,
    ),
)


def get_model(name: str) -> ModelInfo | None:
    return next((model for model in MODELS if model.name == name), None)
