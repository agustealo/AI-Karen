"""Read-only production migration and schema status.

Schema evolution authority is exclusively ``supabase/migrations`` and deployment tooling.
This module may inspect migration state; it must never create, alter, drop, or apply schema.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.client import get_database_client

logger = get_logger(__name__)


class MigrationStatus(str, Enum):
    UP_TO_DATE = "up_to_date"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MigrationInfo:
    version: str
    name: str
    applied: bool


@dataclass(frozen=True)
class MigrationValidationReport:
    timestamp: datetime
    overall_status: MigrationStatus
    latest_version: Optional[str]
    applied_versions: List[str] = field(default_factory=list)
    pending_versions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _canonical_migrations_dir() -> Path:
    override = os.getenv("KAREN_MIGRATIONS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[4]
    return repository_root / "supabase" / "migrations"


def _available_migrations() -> List[Path]:
    root = _canonical_migrations_dir()
    if not root.is_dir():
        logger.warning("Canonical migrations directory not found: %s", root)
        return []
    return sorted(root.glob("*.sql"))


class MigrationValidator:
    """Read-only Supabase migration status reader."""

    def __init__(self) -> None:
        self.db_client = get_database_client()

    async def _applied_versions(self) -> List[str]:
        async with self.db_client.async_session_scope() as session:
            result = await session.execute(
                text(
                    "SELECT version::text FROM supabase_migrations.schema_migrations "
                    "ORDER BY version"
                )
            )
            return [str(row[0]) for row in result.fetchall()]

    async def validate_migrations(self) -> MigrationValidationReport:
        files = _available_migrations()
        available = [path.name.split("_", 1)[0] for path in files]
        latest = available[-1] if available else None
        if not available:
            return MigrationValidationReport(
                timestamp=datetime.now(timezone.utc),
                overall_status=MigrationStatus.UNKNOWN,
                latest_version=None,
                errors=["Canonical Supabase migrations directory is empty or unavailable"],
            )

        try:
            applied = await self._applied_versions()
        except Exception as exc:
            logger.warning("Unable to read Supabase migration history: %s", exc)
            return MigrationValidationReport(
                timestamp=datetime.now(timezone.utc),
                overall_status=MigrationStatus.UNKNOWN,
                latest_version=latest,
                errors=[str(exc)],
            )

        applied_set = set(applied)
        pending = [version for version in available if version not in applied_set]
        status = MigrationStatus.PENDING if pending else MigrationStatus.UP_TO_DATE
        return MigrationValidationReport(
            timestamp=datetime.now(timezone.utc),
            overall_status=status,
            latest_version=latest,
            applied_versions=applied,
            pending_versions=pending,
        )

    async def get_state(self) -> dict:
        report = await self.validate_migrations()
        return {
            "current_version": report.applied_versions[-1] if report.applied_versions else None,
            "latest_version": report.latest_version,
            "pending_count": len(report.pending_versions),
            "failed_count": len(report.errors),
            "validation_status": report.overall_status.value,
            "errors": list(report.errors),
        }


_validator: Optional[MigrationValidator] = None


def get_migration_validator() -> MigrationValidator:
    global _validator
    if _validator is None:
        _validator = MigrationValidator()
    return _validator


__all__ = [
    "MigrationInfo",
    "MigrationStatus",
    "MigrationValidationReport",
    "MigrationValidator",
    "get_migration_validator",
]
