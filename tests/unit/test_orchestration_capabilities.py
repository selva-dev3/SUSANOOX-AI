from __future__ import annotations

from typing import Any

import pytest

from susanoox.agent.orchestration.capabilities import CapabilityExecutor, ToolCapability
from susanoox.permissions.policy import PermissionCategory


async def _allow(_name: str, _category: PermissionCategory, _arguments: dict[str, Any]) -> bool:
    return True


async def _operation(arguments: dict[str, Any]) -> str:
    return str(arguments["path"])


@pytest.mark.asyncio
async def test_bound_capability_requires_tool_and_permission_ceiling() -> None:
    executor = CapabilityExecutor(_allow)
    executor.register(ToolCapability("read_file", PermissionCategory.FILE_READ, _operation))

    no_tool = executor.bind(allowed_tools=(), allowed_permissions=(PermissionCategory.FILE_READ,))
    no_permission = executor.bind(allowed_tools=("read_file",), allowed_permissions=())

    with pytest.raises(PermissionError, match="not available"):
        await no_tool.invoke("read_file", {"path": "README.md"})
    with pytest.raises(PermissionError, match="Permission"):
        await no_permission.invoke("read_file", {"path": "README.md"})


@pytest.mark.asyncio
async def test_bound_capability_requires_authorizer_approval() -> None:
    executor = CapabilityExecutor()
    executor.register(ToolCapability("read_file", PermissionCategory.FILE_READ, _operation))
    capabilities = executor.bind(
        allowed_tools=("read_file",),
        allowed_permissions=(PermissionCategory.FILE_READ,),
    )

    with pytest.raises(PermissionError, match="was not granted"):
        await capabilities.invoke("read_file", {"path": "README.md"})


@pytest.mark.asyncio
async def test_approved_bound_capability_executes_registered_tool() -> None:
    executor = CapabilityExecutor(_allow)
    executor.register(ToolCapability("read_file", PermissionCategory.FILE_READ, _operation))
    capabilities = executor.bind(
        allowed_tools=("read_file",),
        allowed_permissions=(PermissionCategory.FILE_READ,),
    )

    assert await capabilities.invoke("read_file", {"path": "README.md"}) == "README.md"
