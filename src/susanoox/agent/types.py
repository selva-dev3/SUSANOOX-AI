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
    "planning",
    "plan_ready",
    "context_started",
    "context_ready",
    "summarizing",
    "summary_ready",
    "retrying",
    "waiting",
    "completed",
    "failed",
]


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AgentEventKind
    message: str = Field(min_length=1, max_length=500)
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
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
