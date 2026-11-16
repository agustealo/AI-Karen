"""Read-only PostgreSQL source and consent evidence for KCM training admission.

This resolver verifies *only* canonical memory provenance and purpose-scoped
consent. It intentionally supplies no training rights, verified target, or
quality labels. Therefore it cannot approve training in isolation. Those
requirements must be implemented by independent, governed authorities before
any candidate is approved. Never infer them from runtime execution success.
"""

from __future__ import annotations

import hmac
import re
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.consent_filter import recallable_memory_event
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
)

from .training_admission import VerifiedTrainingEvidence

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_SENSITIVITY = frozenset({"normal", "public", "internal"})
_TRAINING_OBJECTIVES = frozenset({
    "persona_expression", "procedural_skill", "verified_correction",
})
_BLOCKED_TAGS = frozenset({
    "no_training", "no_export", "sensitive", "restricted", "prohibited",
})


def _source_prohibits_training(event: MemoryEvent) -> bool:
    """Consult canonical ledger content; detached artifact tags are not authority."""
    if event.event_type != "memory_persisted":
        return True
    payload = event.payload
    if not isinstance(payload, dict):
        return True
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return True
    custom = metadata.get("custom") or {}
    if not isinstance(custom, dict):
        return True
    for values in (
        payload.get("privacy_tags"),
        metadata.get("tags"),
        custom.get("privacy_tags"),
    ):
        if values is None:
            continue
        if not isinstance(values, (list, tuple, set)):
            return True
        if _BLOCKED_TAGS.intersection(
            str(getattr(value, "value", value)).strip().lower()
            for value in values
        ):
            return True
    if any(
        str(getattr(value, "value", value) or "").strip().lower() == "ineligible"
        for value in (
            payload.get("training_eligibility"),
            metadata.get("training_eligibility"),
            custom.get("training_eligibility"),
        )
    ):
        return True
    return custom.get("no_training") is True or custom.get("propagation_allowed") is False


class PostgresTrainingEvidenceResolver:
    """Consume host-governed memory/consent facts without granting trainability.

    A memory event UUID is the source identity and its canonical payload_hash
    is the immutable revision. Separate KCM-purpose consent is mandatory.
    The SQL transaction carries both tenant and user RLS context, while the
    predicates independently enforce owner scope.
    """

    def __init__(
        self,
        *,
        transaction_factory: Callable[..., AbstractAsyncContextManager[Any]] = (
            async_transaction_scope
        ),
    ) -> None:
        self._transaction_factory = transaction_factory

    async def resolve(
        self,
        *,
        tenant_id: str,
        user_id: str,
        source_ref: str,
        source_revision: str,
        objective: str,
    ) -> VerifiedTrainingEvidence | None:
        if objective not in _TRAINING_OBJECTIVES:
            return None
        try:
            tenant = uuid.UUID(str(tenant_id))
            user = uuid.UUID(str(user_id))
            source = uuid.UUID(str(source_ref))
        except (TypeError, ValueError, AttributeError):
            return None
        digest = str(source_revision).strip().lower()
        if not _DIGEST.fullmatch(digest):
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        consent_scope = f"kcm.training.{objective}"
        async with self._transaction_factory(
            tenant_id=str(tenant), user_id=str(user),
        ) as session:
            event = (
                await session.execute(
                    select(MemoryEvent).where(
                        MemoryEvent.event_id == source,
                        MemoryEvent.event_type == "memory_persisted",
                        recallable_memory_event(
                            tenant_id=tenant, user_id=user, now=now,
                        ),
                    )
                )
            ).scalar_one_or_none()
            if event is None or _source_prohibits_training(event):
                return None
            stored_digest = str(event.payload_hash or "").strip().lower()
            if not _DIGEST.fullmatch(stored_digest) or not hmac.compare_digest(
                stored_digest, digest
            ):
                return None
            # NeuroVault stores a parent memory/assertion ID, not normally
            # the ledger event UUID. Preserve owner-scoped legacy event-ID
            # references while resolving the canonical assertion identity.
            superseding_event = (
                await session.execute(
                    select(MemoryEvent.event_id).where(
                        MemoryEvent.tenant_id == tenant,
                        MemoryEvent.user_id == user,
                        or_(
                            MemoryEvent.supersedes == source,
                            MemoryEvent.supersedes.in_(
                                select(MemoryAssertion.assertion_id).where(
                                    MemoryAssertion.event_id == source,
                                    MemoryAssertion.tenant_id == tenant,
                                    MemoryAssertion.user_id == user,
                                )
                            ),
                        ),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            current = superseding_event is None

            consent = (
                await session.execute(
                    select(ConsentScope).where(
                        ConsentScope.tenant_id == tenant,
                        ConsentScope.user_id == user,
                        ConsentScope.scope_name == consent_scope,
                    ).order_by(
                        ConsentScope.granted_at.desc(),
                        ConsentScope.scope_id.desc(),
                    ).limit(1)
                )
            ).scalar_one_or_none()

        consent_valid = bool(
            consent is not None
            and consent.is_granted is True
            and consent.revoked_at is None
        )
        sensitivity = str(event.sensitivity_class or "").strip().lower()
        return VerifiedTrainingEvidence(
            tenant_id=str(tenant),
            user_id=str(user),
            source_ref=str(source),
            source_revision=digest,
            objective=objective,
            verification_receipt_id="",
            consent_receipt_id=(
                str(consent.scope_id) if consent_valid else ""
            ),
            rights_receipt_id="",
            target_ref="",
            source_valid=True,
            target_verified=False,
            consent_valid=consent_valid,
            rights_valid=False,
            sensitivity_cleared=sensitivity in _ALLOWED_SENSITIVITY,
            current=current,
            dimensions={},
        )


__all__ = ["PostgresTrainingEvidenceResolver"]
