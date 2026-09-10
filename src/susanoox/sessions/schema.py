from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from susanoox.agent.types import utc_now
from susanoox.config.settings import ModelName
from susanoox.models.protocol import ConversationMessage, MessageRole


class StoredMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=0)
    role: MessageRole
    content: str
    had_images: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    def conversation_message(self) -> ConversationMessage:
        return ConversationMessage(role=self.role, content=self.content)


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: int = Field(default=1, ge=1)
    title: str = Field(min_length=1, max_length=160)
    project_root: str
    model: ModelName
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived: bool = False
