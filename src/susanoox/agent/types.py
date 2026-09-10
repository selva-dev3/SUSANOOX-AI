from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class PlanStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class TaskKind(StrEnum):
    CONVERSATION = "conversation"
    SEARCH = "search"
    EXPLAIN = "explain"
    VALIDATE = "validate"
    EDIT = "edit"
    TEST_GENERATION = "test_generation"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActivityStatus(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    RETRYING = "retrying"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskBudget(BaseModel):
    """Hard limits shared by future executable task workflows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_iterations: int = Field(default=12, ge=1, le=50)
    max_corrections: int = Field(default=3, ge=0, le=10)
    timeout_seconds: float = Field(default=900.0, gt=0, le=7_200)


class AgentTask(BaseModel):
    """Public task state; this never contains private model reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(min_length=1, max_length=200)
    kind: TaskKind
    objective: str = Field(min_length=1, max_length=2_000)
    status: TaskStatus = TaskStatus.PENDING
    budget: TaskBudget = Field(default_factory=TaskBudget)
    plan_id: str | None = None
    workspace_revision: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    expected_result: str = Field(min_length=1, max_length=500)
    tool_categories: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    version: int = Field(default=1, ge=1)
    objective: str = Field(min_length=1, max_length=2_000)
    status: PlanStatus = PlanStatus.AWAITING_APPROVAL
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    validation_strategy: tuple[str, ...] = ()
    context_snapshot_id: str | None = None
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=20)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


AgentEventKind = Literal[
    "thinking",
    "understanding",
    "searching",
    "planning",
    "plan_ready",
    "context_started",
    "context_ready",
    "reading",
    "editing",
    "command",
    "testing",
    "typecheck",
    "lint",
    "build",
    "diagnosing",
    "summarizing",
    "summary_ready",
    "retrying",
    "refactoring",
    "documentation",
    "waiting",
    "completed",
    "failed",
    "cancelled",
]


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str | None = Field(default=None, max_length=200)
    kind: AgentEventKind
    status: ActivityStatus = ActivityStatus.ACTIVE
    message: str = Field(min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=2_000)
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AttemptRecord(BaseModel):
    """Persisted retry metadata; error bodies are deliberately excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    action: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
