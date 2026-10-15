"""Authorized, evidence-preserving reconciliation of legacy profile projection keys.

NeuroVault's memory_event remains immutable canonical evidence. This adapter
only attaches deterministic MI-04 keys to provably unique *current* derived
ProfileFact rows. It does not infer truth, adjudicate competing beliefs, or
alter consent, chronology, supersession, or semantic content.

The caller must provide an already-authorized VaultContext, with an explicit
memory.maintenance capability and identity-bound policy. No route or startup
code invokes this maintenance procedure automatically.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.core.memory.semantic_contract import profile_projection_key
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

from .derived_projector import PostgresDerivedMemoryProjector
from .ledger_models import ConsentScope, MemoryEvent, ProfileFact
from .vault import PostgresNeuroVault

logger = logging.getLogger(__name__)

MAX_LANE_ROWS = 1000


@dataclass(frozen=True, slots=True)
class ProfileReconciliationReport:
    """Aggregate-only status, deliberately excluding sensitive profile values."""

    scanned: int
    eligible: int
    updated: int
    dry_run: bool
    blocked: dict[str, int]


def _require_maintenance_authority(context: VaultContext) -> tuple[uuid.UUID, uuid.UUID]:
    """Only RuntimePolicy-governed maintenance can inspect or mutate projections."""
    context.validate()
    PostgresNeuroVault._require_capability(context, "memory.maintenance")
    policy = dict(context.policy_context or {})
    if not context.actor_id or not str(context.actor_id).strip():
        raise PermissionError("profile reconciliation requires audited actor identity")
    if (
        str(policy.get("authorized_tenant_id") or "") != context.tenant_id
        or str(policy.get("authorized_user_id") or "") != context.user_id
    ):
        raise PermissionError("profile reconciliation requires authorized tenant/user scope")
    try:
        return uuid.UUID(context.tenant_id), uuid.UUID(context.user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("profile reconciliation requires valid UUID scope") from exc


def _provenance_issue(
    row: ProfileFact,
    event: MemoryEvent | None,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    consent: dict[str, bool],
    now: datetime,
) -> str | None:
    """Validate the original, scoped, currently consented event and its evidence."""
    if event is None or event.tenant_id != tenant_id or event.user_id != user_id:
        return "missing_or_cross_scope_event"
    if event.consent_state != "granted":
        return "revoked_event"
    if (event.valid_to is not None and event.valid_to <= now) or (
        event.valid_from is not None and event.valid_from > now
    ):
        return "inactive_event"
    if row.valid_from is not None and row.valid_from > now:
        return "future_projection"
    if row.source_type != event.source_type:
        return "source_mismatch"

    payload = event.payload
    if not isinstance(payload, dict):
        return "unverifiable_evidence"
    custom = (payload.get("metadata") or {}).get("custom") if isinstance(
        payload.get("metadata"), dict
    ) else None
    if not isinstance(custom, dict):
        return "unverifiable_evidence"
    semantics = custom.get("signal_semantics", custom)
    if not isinstance(semantics, dict):
        return "unverifiable_evidence"
    if semantics.get("category") != row.category or semantics.get("attribute") != row.attribute:
        return "unverifiable_semantics"
    if not isinstance(row.value, dict) or not isinstance(row.value.get("text"), str):
        return "unverifiable_evidence"
    if payload.get("content") != row.value["text"]:
        return "evidence_text_mismatch"
    expected_value = semantics.get("normalized_value")
    if expected_value is not None and expected_value != row.value.get("value"):
        return "evidence_value_mismatch"
    for field in (
        "preference_key", "domain", "facet", "project_id", "task_id",
        "task_type", "location", "cardinality",
    ):
        if field in row.value and row.value[field] != semantics.get(field):
            return "evidence_scope_mismatch"

    vault = payload.get("vault")
    if not isinstance(vault, dict):
        return "unverifiable_evidence"
    scope = vault.get("consent_scope")
    if not isinstance(scope, str) or not scope.strip():
        return "unverifiable_evidence"
    if consent.get(scope) is False:
        return "revoked_consent_scope"
    return None


async def reconcile_profile_projection_lane(
    *,
    context: VaultContext,
    category: str,
    attribute: str,
    apply: bool = False,
    max_rows: int = MAX_LANE_ROWS,
) -> ProfileReconciliationReport:
    """Audit a single tenant/user/category/attribute lane and optionally key it.

    A qualifying row must have evidence-backed identical projection semantics,
    active consent, and no other current fact occupying its logical slot.
    Conflicting or unverifiable rows are never modified. All lane reads and
    updates happen in one transaction under the same advisory lock as regular
    projection writes, plus PostgreSQL's partial unique index.
    """
    tenant_id, user_id = _require_maintenance_authority(context)
    if not isinstance(category, str) or not category.strip():
        raise ValueError("profile category is required")
    if not isinstance(attribute, str) or not attribute.strip():
        raise ValueError("profile attribute is required")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_LANE_ROWS:
        raise ValueError("invalid bounded reconciliation lane size")
    category, attribute = category.strip(), attribute.strip()
    lock_id = PostgresDerivedMemoryProjector._profile_projection_lock_id(
        tenant_id=str(tenant_id), user_id=str(user_id),
        category=category, attribute=attribute,
    )
    blocked: Counter[str] = Counter()
    eligible: list[tuple[ProfileFact, str]] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_transaction_scope(tenant_id=str(tenant_id)) as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id},
        )
        rows = (
            await session.execute(
                select(ProfileFact)
                .where(
                    ProfileFact.tenant_id == tenant_id,
                    ProfileFact.user_id == user_id,
                    ProfileFact.category == category,
                    ProfileFact.attribute == attribute,
                    ProfileFact.valid_to.is_(None),
                )
                .order_by(ProfileFact.fact_id)
                .limit(max_rows + 1)
                .with_for_update()
            )
        ).scalars().all()
        if len(rows) > max_rows:
            raise ValueError("profile reconciliation lane exceeds bounded scan size")
        if not rows:
            return ProfileReconciliationReport(0, 0, 0, not apply, {})

        event_ids = {row.event_id for row in rows}
        events = (
            await session.execute(
                select(MemoryEvent).where(
                    MemoryEvent.event_id.in_(event_ids),
                    MemoryEvent.tenant_id == tenant_id,
                    MemoryEvent.user_id == user_id,
                )
            )
        ).scalars().all()
        events_by_id = {event.event_id: event for event in events}

        consent_records = (
            await session.execute(
                select(ConsentScope).where(
                    ConsentScope.tenant_id == tenant_id,
                    ConsentScope.user_id == user_id,
                ).order_by(ConsentScope.granted_at.desc())
            )
        ).scalars().all()
        consent: dict[str, bool] = {}
        for item in consent_records:
            consent.setdefault(item.scope_name, bool(item.is_granted))

        # All existing current rows participate in collision detection,
        # including revoked/unverifiable rows and already-keyed incumbents.
        grouped: dict[str, list[ProfileFact]] = defaultdict(list)
        issue_by_id: dict[uuid.UUID, str] = {}
        key_by_id: dict[uuid.UUID, str] = {}
        for row in rows:
            try:
                expected = profile_projection_key(
                    tenant_id=str(tenant_id), user_id=str(user_id),
                    category=row.category, attribute=row.attribute,
                    value=row.value, source_event_id=str(row.event_id),
                )
            except (TypeError, ValueError):
                issue_by_id[row.fact_id] = "invalid_profile_identity"
                continue
            key_by_id[row.fact_id] = expected
            grouped[expected].append(row)
            if row.projection_key is not None and row.projection_key != expected:
                # A pre-existing inconsistent keyed slot is a database-integrity
                # incident. Refuse the whole lane, including any safe-looking rows.
                raise ValueError("profile projection contains mismatched keyed identity")
            if row.projection_key is None:
                issue = _provenance_issue(
                    row, events_by_id.get(row.event_id),
                    tenant_id=tenant_id, user_id=user_id,
                    consent=consent, now=now,
                )
                if issue:
                    issue_by_id[row.fact_id] = issue

        for row in rows:
            if row.projection_key is not None:
                continue
            issue = issue_by_id.get(row.fact_id)
            if issue:
                blocked[issue] += 1
                continue
            expected = key_by_id[row.fact_id]
            if len(grouped[expected]) != 1:
                blocked["duplicate_current_slot"] += 1
                continue
            eligible.append((row, expected))

        if apply:
            for row, expected in eligible:
                row.projection_key = expected
            await session.flush()

    report = ProfileReconciliationReport(
        scanned=len(rows), eligible=len(eligible),
        updated=len(eligible) if apply else 0,
        dry_run=not apply, blocked=dict(sorted(blocked.items())),
    )
    logger.info(
        "memory.profile.reconciliation",
        extra={
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "actor_id": context.actor_id,
            "scanned": report.scanned,
            "eligible": report.eligible,
            "updated": report.updated,
            "dry_run": report.dry_run,
            "blocked": report.blocked,
        },
    )
    return report


__all__ = ["ProfileReconciliationReport", "reconcile_profile_projection_lane"]
