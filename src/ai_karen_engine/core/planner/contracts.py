"""Typed personal commitment contracts, independent of automation execution.

This module defines data shapes only. The canonical planner repository and
runtime authorization boundary must be implemented before mutation is exposed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommitmentStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PersonalCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    owner_id: UUID
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10_000)
    status: CommitmentStatus = CommitmentStatus.TODO
    priority: Literal["low", "normal", "high"] = "normal"
    due_at: datetime | None = None
    timezone: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> "PersonalCommitment":
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        for value in (self.due_at, self.created_at, self.updated_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Planner datetimes must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")
        return self


class CommitmentMutation(BaseModel):
    """Request contract, not proof that a planner write succeeded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: UUID
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    status: CommitmentStatus | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def validate_due_at(self) -> "CommitmentMutation":
        if self.due_at is not None and (
            self.due_at.tzinfo is None or self.due_at.utcoffset() is None
        ):
            raise ValueError("Planner due_at must be timezone-aware")
        return self


class PersistedCommitmentReceipt(BaseModel):
    """Only the future authorized repository may issue this after commit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commitment_id: UUID
    tenant_id: UUID
    revision: int = Field(ge=1)
    idempotency_key: UUID
    persisted_at: datetime
    correlation_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_persisted_at(self) -> "PersistedCommitmentReceipt":
        if self.persisted_at.tzinfo is None or self.persisted_at.utcoffset() is None:
            raise ValueError("Receipt timestamp must be timezone-aware")
        return self
