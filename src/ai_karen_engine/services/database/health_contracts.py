from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Literal

HealthStatus = Literal["healthy", "degraded", "unavailable", "disabled", "unknown"]
TierName = Literal["postgres", "redis", "duckdb", "leangraph", "minio"]


class StorageTierHealth(BaseModel):
    tier: TierName
    status: HealthStatus
    enabled: bool
    connected: bool
    latency_ms: float | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    circuit_breaker_state: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryWritebackHealth(BaseModel):
    status: HealthStatus
    enabled: bool
    queue_depth: int | None = None
    pending_count: int | None = None
    failed_count: int | None = None
    last_write_at: str | None = None
    last_failure_at: str | None = None
    writeback_status: str | None = None
    degraded_reason: str | None = None


class ProjectionHealth(BaseModel):
    name: str
    target_tier: TierName
    status: HealthStatus
    lag_count: int | None = None
    last_projected_at: str | None = None
    failed_count: int | None = None
    retry_available: bool = False


class MigrationHealth(BaseModel):
    status: HealthStatus
    current_version: str | None = None
    latest_version: str | None = None
    pending_count: int = 0
    failed_count: int = 0
    validation_status: str | None = None


class DatabaseOperationsOverview(BaseModel):
    status: HealthStatus
    generated_at: str
    correlation_id: str
    request_id: str
    storage_tiers: list[StorageTierHealth]
    memory_writeback: MemoryWritebackHealth
    projections: list[ProjectionHealth]
    migrations: MigrationHealth
    warnings: list[str] = Field(default_factory=list)
    actions_available: list[str] = Field(default_factory=list)
