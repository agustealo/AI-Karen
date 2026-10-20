"""Runtime-facing personal planner action contract.

This module does not parse natural language or select tools. CORTEX and
ChatRuntime must authorize the action and pass verified session identity.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlannerAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"


class AuthorizedPlannerAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: PlannerAction
    idempotency_key: UUID
    correlation_id: str = Field(min_length=1, max_length=128)
    explicit_user_authorization: bool
    commitment_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_action(self) -> "AuthorizedPlannerAction":
        if not self.explicit_user_authorization:
            raise ValueError("Explicit user authorization required for planner mutation")
        if self.action is PlannerAction.CREATE and (
            self.commitment_id is not None
            or self.expected_revision is not None
            or self.title is None
            or self.timezone is None
        ):
            raise ValueError("Create requires title and timezone, not revision")
        if self.action is PlannerAction.UPDATE and (
            self.commitment_id is None or self.expected_revision is None
            or self.title is None or self.timezone is not None
        ):
            raise ValueError("Update requires identity, revision and title")
        return self
