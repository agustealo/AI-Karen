"""MI-08: real PostgreSQL proves atomic task ownership and stale-result fencing."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import Base
from ai_karen_engine.persistence.repositories.automation_repository import SqlAutomationRepository


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="Requires isolated CI PostgreSQL with migrated memory tables",
    ),
]


async def test_sql_atomic_claim_recovery_and_old_owner_fencing():
    import asyncpg

    database_url = os.environ["DATABASE_URL"]
    connection = await asyncpg.connect(database_url)
    tenant, foreign_tenant, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    task_id = f"test-mi08-{uuid.uuid4().hex[:16]}"
    repo = SqlAutomationRepository()
    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "supabase/migrations/"
        "20261016010000_28_automation_task_fenced_claims.sql"
    ).read_text(encoding="utf-8")

    # This job has an isolated PostgreSQL service. Do not modify an existing
    # deployment table or rely on runtime DDL in production code.
    exists = await connection.fetchval(
        "SELECT to_regclass('public.automation_tasks') IS NOT NULL"
    )
    if exists:
        await connection.close()
        pytest.skip("Refusing destructive test DDL on existing automation schema")
    try:
        await connection.execute(
            """
            CREATE TABLE public.automation_tasks (
                task_id text PRIMARY KEY,
                tenant_id uuid NOT NULL,
                created_by uuid NOT NULL,
                name text NOT NULL,
                description text NOT NULL,
                primary_agent text NOT NULL,
                primary_agent_instructions text NOT NULL DEFAULT '',
                task_type text NOT NULL,
                sub_agents jsonb NOT NULL DEFAULT '[]'::jsonb,
                status varchar(32) NOT NULL DEFAULT 'Pending',
                last_run_at timestamptz,
                last_error text,
                run_count integer NOT NULL DEFAULT 0,
                runtime_task_id text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(migration)
        review_migration = (
            root / "supabase/migrations/"
            "20261016020000_29_saved_task_completion_review.sql"
        ).read_text(encoding="utf-8")
        await connection.execute(review_migration)
        await connection.execute(
            """
            ALTER TABLE public.automation_tasks ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.automation_tasks FORCE ROW LEVEL SECURITY;
            CREATE POLICY automation_tasks_tenant_scope
              ON public.automation_tasks FOR ALL
              USING (
                tenant_id = NULLIF(
                  current_setting('app.current_tenant_id', true), ''
                )::uuid
              )
              WITH CHECK (
                tenant_id = NULLIF(
                  current_setting('app.current_tenant_id', true), ''
                )::uuid
              )
            """
        )
        await connection.execute(
            """
            INSERT INTO public.automation_tasks (
                task_id, tenant_id, created_by,
                name, description, primary_agent, task_type
            ) VALUES ($1, $2, $3, 'proof', 'one owner', 'assistant', 'proof')
            """,
            task_id, tenant, user,
        )
        lease_1, lease_2, lease_3 = (str(uuid.uuid4()) for _ in range(3))
        outcomes = await asyncio.gather(
            repo.mark_task_running(
                task_id, str(tenant), claim_token=lease_1, lease_seconds=60,
            ),
            repo.mark_task_running(
                task_id, str(tenant), claim_token=lease_2, lease_seconds=60,
            ),
        )
        assert sum(result is not None for result in outcomes) == 1
        winner = lease_1 if outcomes[0] is not None else lease_2
        loser = lease_2 if winner == lease_1 else lease_1

        assert await repo.get_task(task_id, str(foreign_tenant)) is None
        assert await repo.renew_task_claim(
            task_id, str(tenant), claim_token=loser, lease_seconds=60,
        ) is False
        assert await repo.complete_task(
            task_id, str(tenant),
            claim_token=loser, status="ReviewRequired", last_error=None,
        ) is None
        assert await repo.renew_task_claim(
            task_id, str(tenant), claim_token=winner, lease_seconds=60,
        )

        # Lease expiry permits recovery. Old worker stays fenced, including
        # after the recovered worker has produced its real runtime result.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                text(
                    """
                    UPDATE public.automation_tasks
                    SET claim_expires_at = now() - interval '1 second'
                    WHERE task_id = :task_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"task_id": task_id, "tenant_id": str(tenant)},
            )
        assert await repo.renew_task_claim(
            task_id, str(tenant), claim_token=winner, lease_seconds=60,
        ) is False
        recovered = await repo.mark_task_running(
            task_id, str(tenant), claim_token=lease_3, lease_seconds=60,
        )
        assert recovered is not None
        assert recovered["runCount"] == 2
        assert await repo.complete_task(
            task_id, str(tenant),
            claim_token=winner, status="ReviewRequired", last_error=None,
        ) is None
        terminal = await repo.complete_task(
            task_id, str(tenant),
            claim_token=lease_3, status="ReviewRequired", last_error=None,
            runtime_task_id="correlation-verified",
        )
        assert terminal is not None
        assert terminal["status"] == "ReviewRequired"
        assert terminal["executionId"] == lease_3
        assert await repo.review_task(
            task_id, str(tenant), user_id=str(uuid.uuid4()),
            execution_id=lease_3, decision="approve", note="wrong reviewer",
        ) is None
        reviewed = await repo.review_task(
            task_id, str(tenant), user_id=str(user), execution_id=lease_3,
            decision="approve", note="Verified the recorded result",
        )
        assert reviewed is not None
        assert reviewed["status"] == "Success"
        assert reviewed["reviewedBy"] == str(user)
        assert await repo.review_task(
            task_id, str(tenant), user_id=str(user), execution_id=lease_3,
            decision="approve", note="second approval",
        ) is None
        assert terminal["runtimeTaskId"] == "correlation-verified"

        # A legacy Running record with no ownership is NOT silently stolen.
        await connection.execute(
            """
            UPDATE public.automation_tasks
            SET status='Running', claim_token=NULL, claim_expires_at=NULL
            WHERE task_id=$1
            """,
            task_id,
        )
        assert await repo.mark_task_running(
            task_id, str(tenant), claim_token=str(uuid.uuid4()),
            lease_seconds=60,
        ) is None
    finally:
        await connection.execute("DROP TABLE IF EXISTS public.automation_tasks")
        await connection.close()
