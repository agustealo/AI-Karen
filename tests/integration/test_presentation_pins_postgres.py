"""KUI-002D2: real PostgreSQL authorization and revision acceptance.

Only uses a dedicated disposable /karen_presentation_pin_test database.
No test ever modifies an existing application schema or production data.
These tests deliberately exercise the actual migration SQL and PostgreSQL
foreign keys/RLS, rather than treating mocks as database security proof.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio


async def test_pin_ledger_real_postgres_rls_fk_cas_rollback_and_deletion() -> None:
    if (
        os.environ.get("KAREN_TEST_PIN_POSTGRES") != "1"
        or os.environ.get("KAREN_TEST_DISPOSABLE_DATABASE") != "1"
    ):
        pytest.skip("Pin ledger requires explicit disposable PostgreSQL opt-in")
    dsn = os.environ.get("KAREN_TEST_PIN_DATABASE_URL")
    if not dsn:
        pytest.fail("Explicit disposable pin test database URL is required")
    if urlparse(dsn).path != "/karen_presentation_pin_test":
        pytest.fail("Pin test must use exactly /karen_presentation_pin_test")

    raw = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    suffix = uuid.uuid4().hex[:12]
    backend = "pin_backend_" + suffix
    client = "pin_client_" + suffix
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    thread_a, thread_b = uuid.uuid4(), uuid.uuid4()
    message_a, message_b = uuid.uuid4(), uuid.uuid4()
    created_roles = False
    created_schema = False

    async def execute_as_owner(sql: str, *, tenant: uuid.UUID, user: uuid.UUID,
                               args: tuple = ()):
        # Transaction-local setting + PostgreSQL RLS enforced on a restricted
        # application role, never the migration/table owner.
        async with raw.transaction():
            await raw.execute(f'SET LOCAL ROLE "{backend}"')
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant),
            )
            await raw.execute(
                "SELECT set_config('app.current_user_id', $1, true)",
                str(user),
            )
            return await raw.fetch(sql, *args)

    try:
        existing = await raw.fetchval("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('tenants', 'auth_users', 'conversations',
                                 'messages', 'conversation_presentation_pins')
        """)
        if existing:
            pytest.fail(
                "Pin integration test requires an EMPTY disposable database; "
                "refusing to modify an existing schema"
            )

        await raw.execute("""
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (user_id uuid PRIMARY KEY);
            CREATE TABLE public.conversations (
                conversation_id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL REFERENCES public.tenants(id),
                user_id uuid NOT NULL REFERENCES public.auth_users(user_id)
            );
            CREATE TABLE public.messages (
                message_id uuid PRIMARY KEY,
                conversation_id uuid NOT NULL
                    REFERENCES public.conversations(conversation_id) ON DELETE CASCADE,
                role text NOT NULL,
                content text NOT NULL
            );
        """)
        created_schema = True
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261118213000_64_kui_presentation_pin_references.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        receipt_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261118220000_65_kui_pin_mutation_receipts.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(receipt_migration)
        await raw.execute(
            "INSERT INTO public.tenants (id) VALUES ($1), ($2)",
            tenant_a, tenant_b,
        )
        await raw.execute(
            "INSERT INTO public.auth_users (user_id) VALUES ($1), ($2)",
            owner_a, owner_b,
        )
        await raw.execute(
            "INSERT INTO public.conversations "
            "(conversation_id, tenant_id, user_id) "
            "VALUES ($1,$2,$3),($4,$5,$6)",
            thread_a, tenant_a, owner_a,
            thread_b, tenant_b, owner_b,
        )
        await raw.execute(
            "INSERT INTO public.messages "
            "(message_id, conversation_id, role, content) "
            "VALUES ($1,$2,'assistant','verified'),"
            "($3,$4,'assistant','foreign')",
            message_a, thread_a, message_b, thread_b,
        )

        await raw.execute(f'CREATE ROLE "{backend}" NOLOGIN')
        await raw.execute(f'CREATE ROLE "{client}" NOLOGIN')
        created_roles = True
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{backend}"')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{client}"')
        await raw.execute(
            f'GRANT SELECT ON public.conversations, public.messages TO "{backend}"'
        )
        await raw.execute(
            'GRANT SELECT, INSERT, UPDATE, DELETE '
            f'ON public.conversation_presentation_pins TO "{backend}"'
        )
        await raw.execute(
            'GRANT SELECT, INSERT '
            f'ON public.conversation_presentation_pin_mutation_receipts TO "{backend}"'
        )
        assert not await raw.fetchval("""
            SELECT has_table_privilege($1,
                'public.conversation_presentation_pin_mutation_receipts','SELECT')
        """, client)
        assert not await raw.fetchval("""
            SELECT has_table_privilege($1,
                'public.conversation_presentation_pins','SELECT')
        """, client)

        # The table is empty for a principal with no transaction scope.
        async with raw.transaction():
            await raw.execute(f'SET LOCAL ROLE "{backend}"')
            assert await raw.fetchval(
                "SELECT count(*) FROM public.conversation_presentation_pins"
            ) == 0

        inserted = await execute_as_owner("""
            INSERT INTO public.conversation_presentation_pins
                (tenant_id, user_id, conversation_id, assistant_message_id,
                 presentation_id, evidence_ref, position)
            VALUES ($1, $2, $3, $4, 'time-proof', 'clock-source', 1)
            RETURNING pin_id, revision
        """, tenant=tenant_a, user=owner_a,
            args=(tenant_a, owner_a, thread_a, message_a))
        pin_id = inserted[0]["pin_id"]
        assert inserted[0]["revision"] == 1

        assert len(await execute_as_owner("""
            SELECT pin_id FROM public.conversation_presentation_pins
        """, tenant=tenant_a, user=owner_a)) == 1
        assert not await execute_as_owner("""
            SELECT pin_id FROM public.conversation_presentation_pins
        """, tenant=tenant_b, user=owner_b)

        with pytest.raises(asyncpg.UniqueViolationError):
            await execute_as_owner("""
                INSERT INTO public.conversation_presentation_pins
                    (tenant_id, user_id, conversation_id, assistant_message_id,
                     presentation_id, evidence_ref)
                VALUES ($1,$2,$3,$4,'time-proof','clock-source')
            """, tenant=tenant_a, user=owner_a,
                args=(tenant_a, owner_a, thread_a, message_a))

        # Even a correctly authenticated user cannot link a message
        # belonging to a different canonical conversation.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await execute_as_owner("""
                INSERT INTO public.conversation_presentation_pins
                    (tenant_id, user_id, conversation_id, assistant_message_id,
                     presentation_id, evidence_ref)
                VALUES ($1,$2,$3,$4,'foreign-message','clock-source')
            """, tenant=tenant_a, user=owner_a,
                args=(tenant_a, owner_a, thread_a, message_b))

        with pytest.raises(asyncpg.CheckViolationError):
            await execute_as_owner("""
                INSERT INTO public.conversation_presentation_pins
                    (tenant_id, user_id, conversation_id, assistant_message_id,
                     presentation_id, evidence_ref, position)
                VALUES ($1,$2,$3,$4,'invalid-position','clock-source',100)
            """, tenant=tenant_a, user=owner_a,
                args=(tenant_a, owner_a, thread_a, message_a))

        # Owner B cannot update/delete A's hidden row by guessing pin UUID.
        rows = await execute_as_owner("""
            UPDATE public.conversation_presentation_pins
            SET position=8 WHERE pin_id=$1 RETURNING pin_id
        """, tenant=tenant_b, user=owner_b, args=(pin_id,))
        assert not rows
        rows = await execute_as_owner("""
            DELETE FROM public.conversation_presentation_pins
            WHERE pin_id=$1 RETURNING pin_id
        """, tenant=tenant_b, user=owner_b, args=(pin_id,))
        assert not rows

        assert await execute_as_owner("""
            UPDATE public.conversation_presentation_pins
            SET revision=revision+1, position=5
            WHERE pin_id=$1 AND revision=1 RETURNING revision
        """, tenant=tenant_a, user=owner_a, args=(pin_id,))
        assert not await execute_as_owner("""
            UPDATE public.conversation_presentation_pins
            SET revision=revision+1, position=7
            WHERE pin_id=$1 AND revision=1 RETURNING revision
        """, tenant=tenant_a, user=owner_a, args=(pin_id,))

        # Failed write rolls the prior mutation back to committed position 5.
        with pytest.raises(asyncpg.UniqueViolationError):
            async with raw.transaction():
                await raw.execute(f'SET LOCAL ROLE "{backend}"')
                await raw.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true)",
                    str(tenant_a),
                )
                await raw.execute(
                    "SELECT set_config('app.current_user_id',$1,true)",
                    str(owner_a),
                )
                await raw.execute("""
                    UPDATE public.conversation_presentation_pins
                    SET position=6 WHERE pin_id=$1
                """, pin_id)
                await raw.execute("""
                    INSERT INTO public.conversation_presentation_pins
                        (tenant_id,user_id,conversation_id,assistant_message_id,
                         presentation_id,evidence_ref)
                    VALUES ($1,$2,$3,$4,'time-proof','clock-source')
                """, tenant_a, owner_a, thread_a, message_a)

        row = (await execute_as_owner("""
            SELECT position, revision
            FROM public.conversation_presentation_pins
            WHERE pin_id=$1
        """, tenant=tenant_a, user=owner_a, args=(pin_id,)))[0]
        assert row["position"] == 5
        assert row["revision"] == 2

        # Exactly-once mutation receipt identity, owner RLS and atomic rollback
        # must be real PostgreSQL behavior, not a mocked SQL rowcount.
        receipt_key = uuid.uuid4()
        receipt_sql = """
            INSERT INTO public.conversation_presentation_pin_mutation_receipts
                (tenant_id, user_id, idempotency_key, request_id,
                 correlation_id, request_digest, operation, outcome,
                 pin_id, expected_revision, committed_revision)
            VALUES ($1,$2,$3,'request-reorder','trace-reorder',$4,
                    'reorder','reordered',$5,1,2)
            RETURNING receipt_id
        """
        inserted_receipt = await execute_as_owner(
            receipt_sql, tenant=tenant_a, user=owner_a,
            args=(tenant_a, owner_a, receipt_key, "a" * 64, pin_id),
        )
        assert len(inserted_receipt) == 1
        assert not await execute_as_owner("""
            SELECT receipt_id FROM public.conversation_presentation_pin_mutation_receipts
        """, tenant=tenant_b, user=owner_b)
        with pytest.raises(asyncpg.UniqueViolationError):
            await execute_as_owner(
                receipt_sql, tenant=tenant_a, user=owner_a,
                args=(tenant_a, owner_a, receipt_key, "b" * 64, pin_id),
            )

        # No receipt can be updated or deleted, even when owner-scoped.
        # A backend with only SELECT/INSERT privileges is already denied.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await execute_as_owner("""
                DELETE FROM public.conversation_presentation_pin_mutation_receipts
                WHERE idempotency_key=$1
            """, tenant=tenant_a, user=owner_a, args=(receipt_key,))

        # The immutable trigger rejects changes even when a privileged
        # maintenance connection has SQL UPDATE/DELETE permission.
        with pytest.raises(asyncpg.PostgresError, match="immutable"):
            async with raw.transaction():
                await raw.execute("""
                    UPDATE public.conversation_presentation_pin_mutation_receipts
                    SET request_id='tampered'
                    WHERE idempotency_key=$1 AND tenant_id=$2 AND user_id=$3
                """, receipt_key, tenant_a, owner_a)
        with pytest.raises(asyncpg.PostgresError, match="immutable"):
            async with raw.transaction():
                await raw.execute("""
                    DELETE FROM public.conversation_presentation_pin_mutation_receipts
                    WHERE idempotency_key=$1 AND tenant_id=$2 AND user_id=$3
                """, receipt_key, tenant_a, owner_a)

        # The idempotency fence is per principal, not global; a different
        # tenant/user may independently use the same client operation key.
        independent = await execute_as_owner("""
            INSERT INTO public.conversation_presentation_pin_mutation_receipts
                (tenant_id,user_id,idempotency_key,request_id,correlation_id,
                 request_digest,operation,outcome,pin_id)
            VALUES ($1,$2,$3,'foreign-request','foreign-trace',$4,
                    'unpin','already_absent',NULL)
            RETURNING receipt_id
        """, tenant=tenant_b, user=owner_b,
            args=(tenant_b, owner_b, receipt_key, "c" * 64))
        assert len(independent) == 1

        # RLS forbids inserting a receipt into a different owner's scope.
        with pytest.raises(asyncpg.PostgresError):
            await execute_as_owner("""
                INSERT INTO public.conversation_presentation_pin_mutation_receipts
                    (tenant_id,user_id,idempotency_key,request_id,correlation_id,
                     request_digest,operation,outcome,pin_id)
                VALUES ($1,$2,$3,'injected-request','injected-trace',$4,
                        'unpin','already_absent',NULL)
            """, tenant=tenant_a, user=owner_a,
                args=(tenant_b, owner_b, uuid.uuid4(), "d" * 64))

        # A failed duplicate receipt INSERT must roll back the corresponding
        # pin position change in that same transaction.
        with pytest.raises(asyncpg.UniqueViolationError):
            async with raw.transaction():
                await raw.execute(f'SET LOCAL ROLE "{backend}"')
                await raw.execute(
                    "SELECT set_config('app.current_tenant_id',$1,true)",
                    str(tenant_a),
                )
                await raw.execute(
                    "SELECT set_config('app.current_user_id',$1,true)",
                    str(owner_a),
                )
                await raw.execute("""
                    UPDATE public.conversation_presentation_pins
                    SET position=9 WHERE pin_id=$1
                """, pin_id)
                await raw.execute(receipt_sql, tenant_a, owner_a,
                                  receipt_key, "b" * 64, pin_id)

        assert (await execute_as_owner("""
            SELECT position FROM public.conversation_presentation_pins
            WHERE pin_id=$1
        """, tenant=tenant_a, user=owner_a, args=(pin_id,)))[0]["position"] == 5
        assert len(await execute_as_owner("""
            SELECT receipt_id FROM public.conversation_presentation_pin_mutation_receipts
        """, tenant=tenant_a, user=owner_a)) == 1

        # Deleting the canonical conversation cascades its pin, leaving
        # no surviving reference that could be reauthorized after deletion.
        await raw.execute(
            "DELETE FROM public.conversations WHERE conversation_id=$1",
            thread_a,
        )
        assert not await execute_as_owner("""
            SELECT pin_id FROM public.conversation_presentation_pins
        """, tenant=tenant_a, user=owner_a)

        # Receipt immutability must not block the governed tenant deletion
        # cascade. Verify the dependent receipt is actually erased by the
        # parent's FK action, rather than relying on a migration comment.
        assert await raw.fetchval("""
            SELECT count(*) FROM public.conversation_presentation_pin_mutation_receipts
            WHERE tenant_id=$1
        """, tenant_a) == 1
        await raw.execute("DELETE FROM public.tenants WHERE id=$1", tenant_a)
        assert await raw.fetchval("""
            SELECT count(*) FROM public.conversation_presentation_pin_mutation_receipts
            WHERE tenant_id=$1
        """, tenant_a) == 0
    finally:
        # Cleanup is restricted to the dedicated database and these test
        # objects; no production or shared schema is ever used.
        try:
            if created_roles:
                await raw.execute(f'DROP OWNED BY "{backend}"')
                await raw.execute(f'DROP OWNED BY "{client}"')
                await raw.execute(f'DROP ROLE "{backend}"')
                await raw.execute(f'DROP ROLE "{client}"')
            if created_schema:
                for table in (
                    "conversation_presentation_pin_mutation_receipts",
                    "conversation_presentation_pins", "messages", "conversations",
                    "auth_users", "tenants",
                ):
                    await raw.execute(f'DROP TABLE IF EXISTS public.{table} CASCADE')
                # PostgreSQL does not drop standalone trigger functions with tables.
                await raw.execute(
                    'DROP FUNCTION IF EXISTS public.prevent_presentation_pin_receipt_mutation()'
                )
        finally:
            await raw.close()
