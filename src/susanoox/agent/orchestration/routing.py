from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import StrEnum

from susanoox.agent.orchestration.models import AgentRole
from susanoox.config.settings import ModelName


class TaskComplexity(StrEnum):
    LIGHT = "light"
    COMPLEX = "complex"


class ModelRouter:
    """Deterministic model selection with a single shared large-model slot."""

    _LARGE_ROLES = frozenset({AgentRole.CODE, AgentRole.REVIEW})

    def __init__(self, *, max_fast_requests: int = 2, max_large_requests: int = 1) -> None:
        if max_fast_requests < 1 or max_fast_requests > 8:
            raise ValueError("max_fast_requests must be from 1 to 8")
        if max_large_requests != 1:
            raise ValueError("max_large_requests must be 1 for the shared GPU")
        self._limits = {
            "susanoox-fast": asyncio.Semaphore(max_fast_requests),
            "susanoox-large": asyncio.Semaphore(max_large_requests),
        }

    def select(self, role: AgentRole, complexity: TaskComplexity) -> ModelName:
        if complexity is TaskComplexity.COMPLEX and role in self._LARGE_ROLES:
            return "susanoox-large"
        return "susanoox-fast"

    @asynccontextmanager
    async def lease(self, model: ModelName) -> AsyncGenerator[None]:
        if model not in self._limits:
            raise ValueError("Orchestration supports only fast and large text models")
        async with self._limits[model]:
            yield
