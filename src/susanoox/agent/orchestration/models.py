from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from susanoox.agent.types import AgentTask, TaskBudget, TaskKind, TaskStatus, utc_now
from susanoox.permissions.policy import PermissionCategory


class RunStatus(StrEnum):
    PENDING = "pending"
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class DependencyCondition(StrEnum):
    REQUIRES_SUCCESS = "requires_success"
    REQUIRES_TERMINAL = "requires_terminal"


class ResourceMode(StrEnum):
    READ = "read"
    WRITE = "write"


class AgentRole(StrEnum):
    CONTEXT = "context"
    CODE = "code"
    TEST = "test"
    VALIDATION = "validation"
    DOCUMENTATION = "documentation"
    REVIEW = "review"


class BackgroundStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)
    status: RunStatus = RunStatus.PENDING
    plan_id: str | None = Field(default=None, max_length=200)
    root_task_id: str | None = Field(default=None, max_length=200)
    workspace_revision: str | None = Field(default=None, max_length=128)
    budget: TaskBudget = Field(default_factory=TaskBudget)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    predecessor_id: str = Field(min_length=1, max_length=200)
    successor_id: str = Field(min_length=1, max_length=200)
    condition: DependencyCondition = DependencyCondition.REQUIRES_SUCCESS


class ResourceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=1_000)
    mode: ResourceMode = ResourceMode.READ


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(default="Completed", max_length=4_000)
    changed_paths: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2_000)
    retryable: bool = False
    user_action_required: bool = False
    fingerprint: str = Field(min_length=64, max_length=64)


class TaskAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = Field(min_length=1, max_length=200)
    ordinal: int = Field(ge=1)
    status: TaskStatus
    model: str | None = Field(default=None, max_length=100)
    error_fingerprint: str | None = Field(default=None, max_length=64)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class SubAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AgentRole
    model: str = Field(default="susanoox-fast", max_length=100)
    allowed_tools: tuple[str, ...] = ()
    allowed_permissions: tuple[PermissionCategory, ...] = ()
    max_context_chars: int = Field(default=20_000, ge=1_000, le=120_000)
    max_iterations: int = Field(default=8, ge=1, le=20)


class SubAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1, max_length=200)
    parent_task_id: str = Field(min_length=1, max_length=200)
    config: SubAgentConfig
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BackgroundTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = Field(default=None, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)
    task_id: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    status: BackgroundStatus = BackgroundStatus.CREATED
    checkpoint: str | None = Field(default=None, max_length=4_000)
    workspace_revision: str | None = Field(default=None, max_length=128)
    result_summary: str | None = Field(default=None, max_length=4_000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments_hash: str = Field(min_length=64, max_length=64)
    risk: Literal["safe", "normal", "sensitive", "dangerous"]
    permission_request_id: str | None = Field(default=None, max_length=200)
    status: TaskStatus = TaskStatus.PENDING
    summary: str | None = Field(default=None, max_length=4_000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    task_id: str | None = Field(default=None, max_length=200)
    event_type: str = Field(min_length=1, max_length=100)
    status: TaskStatus | RunStatus | None = None
    message: str = Field(min_length=1, max_length=500)
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class RecoveryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1, max_length=200)
    task_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=160)
    attempt: int = Field(ge=1)
    outcome: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class TaskProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    terminal: int = Field(ge=0)
    running: int = Field(ge=0)
    blocked: int = Field(ge=0)


TaskOperationResult = TaskResult | str | None


def task_from_plan_step(
    *, run: AgentRun, title: str, kind: TaskKind = TaskKind.CONVERSATION, priority: int = 0
) -> AgentTask:
    return AgentTask(
        session_id=run.session_id,
        run_id=run.id,
        kind=kind,
        objective=title,
        plan_id=run.plan_id,
        priority=priority,
        budget=run.budget,
        workspace_revision=run.workspace_revision,
    )
