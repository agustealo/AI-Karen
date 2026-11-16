"""Read-only PostgreSQL adapter for KCM training-governance ancestry.

This is a derived, user-scoped learning projection. NeuroVault still owns the
memory lifecycle, EchoCore owns training admission, and no result from this
module authorizes model training or model promotion.

The required migration is 20261116190000_58_kcm_training_lineage_revocation.
Unknown or unprovisioned epochs intentionally fail closed in the existing
KCM dataset evidence preflight.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import (
    async_transaction_scope,
)


class KcmGovernanceUnavailable(RuntimeError):
    """The authenticated scope, migration, or source lineage is unavailable."""


@dataclass(frozen=True, slots=True)
class KcmDatasetLineageReference:
    dataset_id: str
    dataset_version: int
    manifest_sha256: str
    lineage_status: str


def _scoped_uuid(value: str, *, field_name: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise KcmGovernanceUnavailable(
            f"{field_name}_invalid"
        ) from exc
    if parsed.int == 0:
        raise KcmGovernanceUnavailable(f"{field_name}_invalid")
    return str(parsed)


def _digest(value: str, *, field_name: str) -> str:
    candidate = str(value or "")
    if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise KcmGovernanceUnavailable(f"{field_name}_invalid")
    return candidate


class PostgresKcmGovernanceReader:
    """Read the canonical derived KCM learning scope under actual RLS context.

    Do not introduce a second epoch cache, Redis fallback, or implicit zero
    when no scope row is present. The SQL itself checks both tenant and owner
    in addition to transaction-scoped RLS claims.
    """

    def __init__(
        self,
        *,
        transaction_factory: Callable[..., AbstractAsyncContextManager[Any]] = (
            async_transaction_scope
        ),
    ) -> None:
        self._transaction_factory = transaction_factory

    async def current_epoch(
        self, *, tenant_id: str, user_id: str
    ) -> int | None:
        """Return a current nonnegative epoch or None when unprovisioned."""
        try:
            tenant = _scoped_uuid(tenant_id, field_name="tenant_id")
            user = _scoped_uuid(user_id, field_name="user_id")
        except KcmGovernanceUnavailable:
            return None

        async with self._transaction_factory(
            tenant_id=tenant, user_id=user,
        ) as session:
            result = await session.execute(
                text(
                    "SELECT deletion_epoch "
                    "FROM public.kcm_training_scope_state "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid) "
                    "AND training_authorized = FALSE"
                ),
                {"tenant_id": tenant, "user_id": user},
            )
            epoch = result.scalar_one_or_none()
        if type(epoch) is not int or epoch < 0:
            return None
        return epoch

    async def affected_datasets(
        self,
        *,
        tenant_id: str,
        user_id: str,
        source_event_id: str,
        source_revision: str,
        limit: int = 100,
    ) -> tuple[KcmDatasetLineageReference, ...]:
        """Inspect scoped quarantined/revoked references, not training data.

        A missing governance scope raises instead of returning a misleading
        empty result. Source identifiers must not be guessed from content.
        """
        tenant = _scoped_uuid(tenant_id, field_name="tenant_id")
        user = _scoped_uuid(user_id, field_name="user_id")
        source = _scoped_uuid(source_event_id, field_name="source_event_id")
        revision = _digest(source_revision, field_name="source_revision")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise KcmGovernanceUnavailable("lineage_limit_invalid")

        async with self._transaction_factory(
            tenant_id=tenant, user_id=user,
        ) as session:
            has_scope = await session.execute(
                text(
                    "SELECT 1 FROM public.kcm_training_scope_state "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid)"
                ),
                {"tenant_id": tenant, "user_id": user},
            )
            if has_scope.scalar_one_or_none() != 1:
                raise KcmGovernanceUnavailable("scope_not_provisioned")

            rows = await session.execute(
                text(
                    "SELECT dataset_id, dataset_version, manifest_sha256, "
                    "lineage_status "
                    "FROM public.kcm_dataset_source_lineage "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid) "
                    "AND source_event_id = CAST(:source_event_id AS uuid) "
                    "AND source_revision = CAST(:source_revision AS char(64)) "
                    "ORDER BY dataset_id, dataset_version LIMIT :limit"
                ),
                {
                    "tenant_id": tenant,
                    "user_id": user,
                    "source_event_id": source,
                    "source_revision": revision,
                    "limit": limit,
                },
            )
            records = rows.mappings().all()

        result: list[KcmDatasetLineageReference] = []
        for row in records:
            status = row["lineage_status"]
            if status not in ("quarantined", "revoked"):
                raise KcmGovernanceUnavailable("lineage_status_invalid")
            result.append(
                KcmDatasetLineageReference(
                    dataset_id=str(row["dataset_id"]),
                    dataset_version=int(row["dataset_version"]),
                    manifest_sha256=_digest(
                        row["manifest_sha256"],
                        field_name="manifest_sha256",
                    ),
                    lineage_status=status,
                )
            )
        return tuple(result)


__all__ = [
    "KcmDatasetLineageReference",
    "KcmGovernanceUnavailable",
    "PostgresKcmGovernanceReader",
]
