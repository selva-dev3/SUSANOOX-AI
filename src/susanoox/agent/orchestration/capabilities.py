from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from susanoox.permissions.policy import PermissionCategory

CapabilityOperation = Callable[[dict[str, Any]], Awaitable[Any]]


CapabilityAuthorizer = Callable[[str, PermissionCategory, dict[str, Any]], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """A trusted tool entry whose permission category cannot be changed by a worker."""

    name: str
    category: PermissionCategory
    operation: CapabilityOperation


class CapabilityExecutor:
    """The only supported bridge from orchestration workers to concrete tools."""

    def __init__(self, authorizer: CapabilityAuthorizer | None = None) -> None:
        self._authorizer = authorizer
        self._tools: dict[str, ToolCapability] = {}

    def register(self, capability: ToolCapability) -> None:
        if capability.name in self._tools:
            raise ValueError(f"A capability is already registered for {capability.name}.")
        self._tools[capability.name] = capability

    def bind(
        self,
        *,
        allowed_tools: tuple[str, ...],
        allowed_permissions: tuple[PermissionCategory, ...],
    ) -> BoundCapabilities:
        return BoundCapabilities(
            executor=self,
            allowed_tools=frozenset(allowed_tools),
            allowed_permissions=frozenset(allowed_permissions),
        )

    async def invoke_scoped(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed_tools: frozenset[str],
        allowed_permissions: frozenset[PermissionCategory],
    ) -> Any:
        capability = self._tools.get(name)
        if capability is None or name not in allowed_tools:
            raise PermissionError(f"Tool capability {name!r} is not available to this worker")
        if capability.category not in allowed_permissions:
            raise PermissionError(
                f"Permission {capability.category!s} is not available to this worker"
            )
        if self._authorizer is None or not await self._authorizer(
            name, capability.category, arguments
        ):
            raise PermissionError(f"Permission was not granted for tool capability {name!r}")
        return await capability.operation(arguments)


@dataclass(frozen=True, slots=True)
class BoundCapabilities:
    """Task-scoped facade that cannot widen its own tool or permission grants."""

    executor: CapabilityExecutor
    allowed_tools: frozenset[str]
    allowed_permissions: frozenset[PermissionCategory]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self.executor.invoke_scoped(
            name,
            arguments,
            allowed_tools=self.allowed_tools,
            allowed_permissions=self.allowed_permissions,
        )
