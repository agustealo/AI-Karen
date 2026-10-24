"""Real PostgreSQL acceptance for tenant-scoped personal planner commits.

Run only on a disposable database with migration 38 applied and seeded
authenticated tenant/user records. Never applies DDL or edits production data.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ai_karen_engine.core.planner.contracts import CommitmentMutation, CommitmentStatus
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.persistence.repositories.personal_planner_repository import (
    PersonalPlannerRepository,
    PlannerConflictError,
    PlannerNotFoundError,
)


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_PLANNER_POSTGRES") != "1"
        or os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1",
        reason="Requires explicitly approved disposable migrated PostgreSQL",
    ),
]


def _scope() -> tuple[UUID, UUID]:
    tenant = os.getenv("KAREN_TEST_PLANNER_TENANT_ID")
    owner = os.getenv("KAREN_TEST_PLANNER_USER_ID")
    if not tenant or not owner:
        pytest.skip("Seed disposable database and provide tenant/user IDs")
    return UUID(tenant), UUID(owner)


async def test_planner_live_idempotency_conflicts_and_owner_isolation():
    tenant, owner = _scope()
    repo = PersonalPlannerRepository()
    key = uuid4()
    cid = "planner-postgres-acceptance"
    first, receipt = await repo.create(
        tenant_id=tenant, owner_id=owner, title="Complete weekly plan",
        timezone="America/Detroit", idempotency_key=key, correlation_id=cid,
    )
    try:
        duplicate, duplicate_receipt = await repo.create(
            tenant_id=tenant, owner_id=owner, title="Complete weekly plan",
            timezone="America/Detroit", idempotency_key=key, correlation_id="retry-cid",
        )
        assert duplicate == first
        assert duplicate_receipt == receipt

        # A new repository instance must read the committed record from storage,
        # not a process-local planner cache.
        reopened = PersonalPlannerRepository()
        assert await reopened.get(
            tenant_id=tenant, owner_id=owner, commitment_id=first.id,
        ) == first

        with pytest.raises(PlannerConflictError):
            await repo.create(
                tenant_id=tenant, owner_id=owner, title="Different task",
                timezone="America/Detroit", idempotency_key=key,
                correlation_id=cid,
            )

        updated = await repo.update(
            tenant_id=tenant, owner_id=owner, commitment_id=first.id,
            mutation=CommitmentMutation(
                idempotency_key=uuid4(), expected_revision=1,
                status=CommitmentStatus.IN_PROGRESS,
            ),
            correlation_id=cid,
        )
        assert updated[0].revision == 2
        assert updated[1].revision == 2

        mutation = CommitmentMutation(
            idempotency_key=uuid4(), expected_revision=2,
            status=CommitmentStatus.COMPLETED,
        )
        finished = await repo.update(
            tenant_id=tenant, owner_id=owner, commitment_id=first.id,
            mutation=mutation, correlation_id=cid,
        )
        assert finished[0].revision == 3
        assert finished[1].revision == 3
        retry = await repo.update(
            tenant_id=tenant, owner_id=owner, commitment_id=first.id,
            mutation=mutation, correlation_id="another-correlation",
        )
        assert retry == finished
        assert (await repo.get(
            tenant_id=tenant, owner_id=owner, commitment_id=first.id
        )).revision == 3

        with pytest.raises(PlannerConflictError):
            await repo.update(
                tenant_id=tenant, owner_id=owner, commitment_id=first.id,
                mutation=CommitmentMutation(
                    idempotency_key=uuid4(), expected_revision=1, title="Stale edit"
                ),
                correlation_id=cid,
            )

        # An invalid receipt write must roll back the preceding mutation.
        # The foreign-key failure deliberately occurs inside one transaction.
        rollback_id = uuid4()
        with pytest.raises(IntegrityError):
            async with async_transaction_scope(str(tenant)) as session:
                await session.execute(text("""
                    INSERT INTO public.personal_planner_commitments
                    (id, tenant_id, owner_id, title, timezone)
                    VALUES (:id, :tenant, :owner, :title, :timezone)
                """), {"id": rollback_id, "tenant": tenant, "owner": owner,
                       "title": "Must roll back", "timezone": "UTC"})
                await session.execute(text("""
                    INSERT INTO public.personal_planner_mutation_receipts
                    (tenant_id, owner_id, idempotency_key, operation, request_fingerprint,
                     commitment_id, result_snapshot, revision, correlation_id)
                    VALUES (:tenant, :owner, :key, 'create', :fingerprint,
                            :unknown_id, CAST(:snapshot AS jsonb), 1, :correlation)
                """), {"tenant": tenant, "owner": owner, "key": uuid4(),
                       "fingerprint": "a" * 64, "unknown_id": uuid4(),
                       "snapshot": "{}", "correlation": cid})
        with pytest.raises(PlannerNotFoundError):
            await reopened.get(
                tenant_id=tenant, owner_id=owner, commitment_id=rollback_id,
            )

        with pytest.raises(PlannerNotFoundError):
            await repo.get(
                tenant_id=tenant, owner_id=uuid4(), commitment_id=first.id,
            )

        # Competing identical create requests must commit a single result.
        concurrent_key = uuid4()
        simultaneous = await asyncio.gather(*[
            repo.create(
                tenant_id=tenant, owner_id=owner,
                title="Single concurrent commitment", timezone="UTC",
                idempotency_key=concurrent_key, correlation_id=f"concurrent-{i}",
            )
            for i in range(2)
        ])
        assert simultaneous[0] == simultaneous[1]
        concurrent_id = simultaneous[0][0].id
        try:
            async with async_transaction_scope(str(tenant)) as session:
                matches = (await session.execute(text("""
                    SELECT count(*) FROM public.personal_planner_mutation_receipts
                    WHERE tenant_id=:tenant AND owner_id=:owner AND idempotency_key=:key
                """), {"tenant": tenant, "owner": owner, "key": concurrent_key})).scalar_one()
            assert matches == 1
        finally:
            async with async_transaction_scope(str(tenant)) as session:
                await session.execute(text("""
                    DELETE FROM public.personal_planner_commitments
                    WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner
                """), {"id": concurrent_id, "tenant": tenant, "owner": owner})

        # A genuinely separate concurrent update can win only one revision.
        competing = await repo.create(
            tenant_id=tenant, owner_id=owner, title="Concurrent edit",
            timezone="UTC", idempotency_key=uuid4(), correlation_id=cid,
        )
        try:
            updates = await asyncio.gather(*[
                repo.update(
                    tenant_id=tenant, owner_id=owner, commitment_id=competing[0].id,
                    mutation=CommitmentMutation(
                        idempotency_key=uuid4(), expected_revision=1,
                        title=f"Edit {index}",
                    ),
                    correlation_id=cid,
                )
                for index in (1, 2)
            ], return_exceptions=True)
            assert sum(isinstance(result, PlannerConflictError) for result in updates) == 1
            assert sum(not isinstance(result, BaseException) for result in updates) == 1
        finally:
            async with async_transaction_scope(str(tenant)) as session:
                await session.execute(text("""
                    DELETE FROM public.personal_planner_commitments
                    WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner
                """), {"id": competing[0].id, "tenant": tenant, "owner": owner})
    finally:
        async with async_transaction_scope(str(tenant)) as session:
            await session.execute(text("""
                DELETE FROM public.personal_planner_commitments
                WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner
            """), {"id": first.id, "tenant": tenant, "owner": owner})


async def test_authorized_planner_presentation_reads_committed_postgres_and_isolates_owner():
    """A fresh service/repository must render only rows owned by the authenticated user."""
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.services.personal_planner import (
        PersonalPlannerService, PlannerAuthorizationError,
    )

    tenant, owner = _scope()
    repo = PersonalPlannerRepository()
    created, _ = await repo.create(
        tenant_id=tenant,
        owner_id=owner,
        title="PostgreSQL planner presentation proof",
        timezone="America/Detroit",
        idempotency_key=uuid4(),
        correlation_id="planner-presentation-db",
    )
    principal = UserData(user_id=str(owner), tenant_id=str(tenant), roles=["user"])
    foreign = UserData(user_id=str(uuid4()), tenant_id=str(tenant), roles=["user"])
    denied = UserData(user_id=str(owner), tenant_id=str(tenant), roles=["readonly"])
    try:
        # Construct a new service and repository after the transaction commits.
        service = PersonalPlannerService(repository=PersonalPlannerRepository())
        result = await service.list_presentation(
            user=principal, correlation_id="planner-db-reopen", limit=20,
        )
        assert result["empty"] is False
        presentation = result["presentation"]
        assert presentation["component_type"] == "planner.task_list"
        own = [task for task in presentation["data"]["tasks"]
               if task["id"] == str(created.id)]
        assert own == [{"id": str(created.id),
                        "title": created.title, "status": created.status.value}]
        assert "owner_id" not in str(presentation)
        assert "tenant_id" not in str(presentation)

        other = await service.list_presentation(
            user=foreign, correlation_id="planner-foreign-read", limit=20,
        )
        assert other == {"presentation": None, "empty": True}

        with pytest.raises(PlannerAuthorizationError):
            await service.list_presentation(
                user=denied, correlation_id="planner-denied-read", limit=20,
            )
    finally:
        async with async_transaction_scope(str(tenant)) as session:
            await session.execute(text("""
                DELETE FROM public.personal_planner_commitments
                WHERE id=:id AND tenant_id=:tenant AND owner_id=:owner
            """), {"id": created.id, "tenant": tenant, "owner": owner})
