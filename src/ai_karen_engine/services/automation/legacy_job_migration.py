"""One-time migration of legacy file-backed automation jobs.

Legacy jobs predate tenant and owner identity, so they cannot be imported safely
by whichever user happens to hit the API first. The migration requires an
explicit durable tenant/user binding, preserves job IDs, verifies PostgreSQL
state, and only then removes the obsolete JSON source.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    get_automation_repository,
)
from ai_karen_engine.services.auth.auth_service import AuthService, UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id

_LEGACY_PATH_ENV = "KAREN_LEGACY_AUTOMATION_JOBS_PATH"
_DEFAULT_LEGACY_PATH = Path("data/automation_jobs.json")


class LegacyAutomationMigrationRequired(RuntimeError):
    """Legacy jobs exist but do not yet have durable tenant/owner identity."""


class LegacyAutomationMigrationError(RuntimeError):
    """Legacy job migration could not be completed safely."""


@dataclass(frozen=True)
class LegacyAutomationMigrationResult:
    source: str
    source_sha256: str
    imported: int
    already_present: int
    removed_source: bool


def get_legacy_job_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return path
    return Path(os.getenv(_LEGACY_PATH_ENV, str(_DEFAULT_LEGACY_PATH))).expanduser()


def _read_legacy_jobs(path: Path) -> tuple[Dict[str, Dict[str, Any]], str]:
    if not path.exists():
        return {}, ""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not raw.strip():
        return {}, digest
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyAutomationMigrationError(
            f"Legacy automation job store is malformed: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise LegacyAutomationMigrationError(
            "Legacy automation job store must contain an object keyed by job ID"
        )

    jobs: Dict[str, Dict[str, Any]] = {}
    for raw_job_id, value in payload.items():
        job_id = str(raw_job_id or "").strip()
        if not job_id or not isinstance(value, dict):
            raise LegacyAutomationMigrationError(
                "Legacy automation job store contains an invalid job record"
            )
        jobs[job_id] = dict(value)
    return jobs, digest


def legacy_job_cutover_required(path: Optional[Path] = None) -> bool:
    jobs, _ = _read_legacy_jobs(get_legacy_job_path(path))
    return bool(jobs)


def assert_legacy_job_cutover_complete(path: Optional[Path] = None) -> None:
    source = get_legacy_job_path(path)
    if legacy_job_cutover_required(source):
        raise LegacyAutomationMigrationRequired(
            "Legacy automation jobs require explicit tenant/owner migration before "
            "durable job operations can continue"
        )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_legacy_job(job_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    tasks = raw.get("tasks") or []
    if not name or not description or not isinstance(tasks, list):
        raise LegacyAutomationMigrationError(
            f"Legacy job {job_id} is missing a valid name, description, or task list"
        )

    status = str(raw.get("status") or "Pending")
    if status == "Running":
        status = "Pending"
    if status not in {"Pending", "Success", "Failed"}:
        status = "Pending"

    return {
        "id": job_id,
        "name": name,
        "description": description,
        "tasks": tasks,
        "trigger": str(raw.get("trigger") or "Manual Run"),
        "status": status,
        "last_results": list(raw.get("last_results") or []),
        "last_run": _parse_datetime(raw.get("last_run")),
        "last_error": raw.get("error") or raw.get("last_error"),
        "created_at": _parse_datetime(raw.get("created_at")),
        "updated_at": _parse_datetime(raw.get("updated_at")),
    }


async def migrate_legacy_jobs(
    *,
    tenant_id: str,
    user_id: str,
    source_path: Optional[Path] = None,
    repository: Optional[SqlAutomationRepository] = None,
    auth_service: Optional[AuthService] = None,
    remove_source: bool = True,
) -> LegacyAutomationMigrationResult:
    """Import legacy jobs under an explicit durable identity and verify the result."""
    try:
        uuid.UUID(str(tenant_id))
        uuid.UUID(str(user_id))
    except ValueError as exc:
        raise LegacyAutomationMigrationError(
            "tenant_id and user_id must be durable UUID identifiers"
        ) from exc

    source = get_legacy_job_path(source_path)
    jobs, digest = _read_legacy_jobs(source)
    if not jobs:
        return LegacyAutomationMigrationResult(
            source=str(source),
            source_sha256=digest,
            imported=0,
            already_present=0,
            removed_source=False,
        )

    auth = auth_service or await get_auth_service()
    owner = await get_fresh_user_by_id(
        auth,
        user_id=str(user_id),
        tenant_id=str(tenant_id),
    )
    if owner is None or owner.status != UserStatus.ACTIVE:
        raise LegacyAutomationMigrationError(
            "Migration owner must be an active user in the destination tenant"
        )

    repo = repository or get_automation_repository()
    imported = 0
    already_present = 0
    for job_id, raw in jobs.items():
        existing = await repo.get_job(job_id, str(tenant_id))
        if existing is not None:
            already_present += 1
            continue
        record = _normalize_legacy_job(job_id, raw)
        await repo.create_job(
            tenant_id=str(tenant_id),
            created_by=str(user_id),
            record=record,
        )
        verified = await repo.get_job(job_id, str(tenant_id))
        if verified is None or str(verified.get("id")) != job_id:
            raise LegacyAutomationMigrationError(
                f"Durable verification failed for legacy job {job_id}"
            )
        imported += 1

    removed_source = False
    if remove_source:
        source.unlink()
        removed_source = True

    return LegacyAutomationMigrationResult(
        source=str(source),
        source_sha256=digest,
        imported=imported,
        already_present=already_present,
        removed_source=removed_source,
    )


__all__ = [
    "LegacyAutomationMigrationError",
    "LegacyAutomationMigrationRequired",
    "LegacyAutomationMigrationResult",
    "assert_legacy_job_cutover_complete",
    "get_legacy_job_path",
    "legacy_job_cutover_required",
    "migrate_legacy_jobs",
]
