"""Canonical tenant-scoped persistence for personal commitments.

Never executes agents, schedules jobs, or forms memories. Routes and runtime
must pass authenticated owner and tenant identities, never model-supplied ones.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from ai_karen_engine.core.planner.contracts import (
    CommitmentMutation,
    PersonalCommitment,
    PersistedCommitmentReceipt,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


class PlannerConflictError(RuntimeError):
    """A revision or idempotency key conflicts with an existing mutation."""


class PlannerNotFoundError(LookupError):
    """No commitment belongs to the authorized tenant and user."""


_COLUMNS = """id, tenant_id, owner_id, project_id, title, description, status,
priority, due_at, timezone, revision, created_at, updated_at"""


class PersonalPlannerRepository:
    async def get(self, *, tenant_id: UUID, owner_id: UUID, commitment_id: UUID) -> PersonalCommitment:
        async with async_transaction_scope(str(tenant_id)) as session:
            row = (await session.execute(
                text(f"""SELECT {_COLUMNS} FROM public.personal_planner_commitments
                            WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner"""),
                {"id": commitment_id, "tenant": tenant_id, "owner": owner_id},
            )).mappings().first()
            if row is None:
                raise PlannerNotFoundError("Commitment unavailable")
            return PersonalCommitment.model_validate(dict(row))

    async def create(
        self, *, tenant_id: UUID, owner_id: UUID, title: str, timezone: str,
        idempotency_key: UUID, correlation_id: str,
    ) -> tuple[PersonalCommitment, PersistedCommitmentReceipt]:
        # Validate input before accessing storage.
        from datetime import datetime, timezone as utc_timezone
        now = datetime.now(utc_timezone.utc)
        draft = PersonalCommitment(
            id=uuid4(), tenant_id=tenant_id, owner_id=owner_id, title=title,
            timezone=timezone, revision=1, created_at=now, updated_at=now,
        )
        if not correlation_id or len(correlation_id) > 128:
            raise ValueError("Valid correlation_id required")
        async with async_transaction_scope(str(tenant_id)) as session:
            existing = (await session.execute(text("""
                SELECT commitment_id FROM public.personal_planner_mutation_receipts
                WHERE tenant_id=:tenant AND owner_id=:owner AND idempotency_key=:key
            """), {"tenant": tenant_id, "owner": owner_id, "key": idempotency_key})).scalar_one_or_none()
            if existing is not None:
                raise PlannerConflictError("Idempotency key has already been used")
            await session.execute(text("""
                INSERT INTO public.personal_planner_commitments
                (id, tenant_id, owner_id, title, timezone, revision, created_at, updated_at)
                VALUES (:id, :tenant, :owner, :title, :timezone, 1, :created, :updated)
            """), {
                "id": draft.id, "tenant": tenant_id, "owner": owner_id,
                "title": draft.title, "timezone": draft.timezone,
                "created": now, "updated": now,
            })
            await session.execute(text("""
                INSERT INTO public.personal_planner_mutation_receipts
                (tenant_id, owner_id, idempotency_key, commitment_id, revision, correlation_id)
                VALUES (:tenant, :owner, :key, :id, 1, :correlation)
            """), {
                "tenant": tenant_id, "owner": owner_id, "key": idempotency_key,
                "id": draft.id, "correlation": correlation_id,
            })
        return draft, PersistedCommitmentReceipt(
            commitment_id=draft.id, tenant_id=tenant_id, revision=1,
            idempotency_key=idempotency_key, persisted_at=now,
            correlation_id=correlation_id,
        )

    async def update(
        self, *, tenant_id: UUID, owner_id: UUID, commitment_id: UUID,
        mutation: CommitmentMutation, correlation_id: str,
    ) -> PersonalCommitment:
        if mutation.expected_revision is None:
            raise ValueError("Update requires expected_revision")
        if not correlation_id or len(correlation_id) > 128:
            raise ValueError("Valid correlation_id required")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        changes = {
            "title": mutation.title, "description": mutation.description,
            "status": mutation.status.value if mutation.status is not None else None,
            "due_at": mutation.due_at,
        }
        # Keep unchanged columns untouched, and require at least one change.
        updates = {key: value for key, value in changes.items() if value is not None}
        if not updates:
            raise ValueError("At least one planner field must change")
        async with async_transaction_scope(str(tenant_id)) as session:
            already = (await session.execute(text("""
                SELECT commitment_id FROM public.personal_planner_mutation_receipts
                WHERE tenant_id=:tenant AND owner_id=:owner AND idempotency_key=:key
            """), {"tenant": tenant_id, "owner": owner_id, "key": mutation.idempotency_key})).scalar_one_or_none()
            if already is not None:
                raise PlannerConflictError("Idempotency key has already been used")
            bind = {
                "id": commitment_id, "tenant": tenant_id, "owner": owner_id,
                "expected": mutation.expected_revision, "updated": now, **updates,
            }
            set_clause = ", ".join(f"{name}=:{name}" for name in updates)
            result = await session.execute(text(f"""
                UPDATE public.personal_planner_commitments
                SET {set_clause}, revision=revision+1, updated_at=:updated
                WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner
                AND revision=:expected
                RETURNING {_COLUMNS}
            """), bind)
            row = result.mappings().first()
            if row is None:
                raise PlannerConflictError("Commitment unavailable or revision changed")
            await session.execute(text("""
                INSERT INTO public.personal_planner_mutation_receipts
                (tenant_id, owner_id, idempotency_key, commitment_id, revision, correlation_id)
                VALUES (:tenant, :owner, :key, :id, :revision, :correlation)
            """), {
                "tenant": tenant_id, "owner": owner_id,
                "key": mutation.idempotency_key, "id": commitment_id,
                "revision": row["revision"], "correlation": correlation_id,
            })
            return PersonalCommitment.model_validate(dict(row))
