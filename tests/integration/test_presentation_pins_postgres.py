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


async def test_pin_ledger_real_postgres_rls_fk_cas_rollback_and_deletion(monkeypatch) -> None:
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
                                 'messages', 'conversation_presentation_pins',
                                 'conversation_presentation_pin_mutation_receipts',
                                 'auth_sessions')
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


        # Execute the ACTUAL new repository SQLAlchemy transaction path, not
        # only raw migration DML. The canonical transaction manager still
        # supplies principal RLS and commit/rollback, while this disposable
        # fixture uses the restricted backend role.
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        import asyncio
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from ai_karen_engine.persistence.postgres import transactions
        from ai_karen_engine.persistence.repositories import presentation_pin_repository
        from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
            PresentationPinConflict,
            PresentationPinRepository,
            PresentationPinUnavailable,
        )

        engine = create_async_engine(
            dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            transactions, "get_postgres_engine",
            lambda: SimpleNamespace(async_session_factory=maker),
        )

        @asynccontextmanager
        async def actual_scoped_role(tenant_id: str, *, user_id: str):
            async with transactions.async_transaction_scope(
                tenant_id, user_id=user_id
            ) as session:
                await session.execute(text(f'SET LOCAL ROLE "{backend}"'))
                yield session

        monkeypatch.setattr(
            presentation_pin_repository, "async_transaction_scope",
            actual_scoped_role,
        )
        repository = PresentationPinRepository()
        async def create_owned_pin(name: str):
            return await raw.fetchval("""
                INSERT INTO public.conversation_presentation_pins
                    (tenant_id,user_id,conversation_id,assistant_message_id,
                     presentation_id,evidence_ref,position)
                VALUES ($1,$2,$3,$4,$5,'runtime-proof',0)
                RETURNING pin_id
            """, tenant_b, owner_b, thread_b, message_b, name)

        def unpin_args(identity, key, req="original"):
            return dict(
                authenticated_tenant_id=str(tenant_b),
                authenticated_user_id=str(owner_b),
                idempotency_key=str(key),
                request_id=req,
                correlation_id="receipt-runtime-postgres",
                operation="unpin",
                pin_id=str(identity),
            )

        try:
            concurrent_pin = await create_owned_pin("runtime-concurrent")
            duplicate_key = uuid.uuid4()
            args = unpin_args(concurrent_pin, duplicate_key)
            # The first transaction holds the canonical principal-wide
            # advisory lock; both concurrent retries must return the EXACT
            # same immutable receipt without duplicate DELETE.
            first, retry = await asyncio.gather(
                repository.mutate_with_receipt(**args),
                repository.mutate_with_receipt(
                    **unpin_args(concurrent_pin, duplicate_key, "retried")
                ),
            )
            assert first.receipt_id == retry.receipt_id
            # Either concurrent request can win the advisory lock. Both must
            # observe the immutable request ID recorded by that winner.
            assert first.request_id == retry.request_id
            assert first.request_id in {"original", "retried"}
            assert first.outcome == retry.outcome == "unpinned"
            assert await raw.fetchval("""
                SELECT count(*) FROM public.conversation_presentation_pins
                WHERE pin_id=$1
            """, concurrent_pin) == 0
            assert await raw.fetchval("""
                SELECT count(*) FROM public.conversation_presentation_pin_mutation_receipts
                WHERE tenant_id=$1 AND user_id=$2 AND idempotency_key=$3
            """, tenant_b, owner_b, duplicate_key) == 1

            # An identical key with a different authenticated operation
            # identity is a conflict, never a second mutation.
            with pytest.raises(PresentationPinConflict):
                await repository.mutate_with_receipt(
                    **unpin_args(uuid.uuid4(), duplicate_key, "conflict")
                )

            # Exercise the canonical signed-JWT -> durable AuthService session
            # -> FastAPI route -> runtime -> actual PostgreSQL receipt path.
            # Both the auth-session query and pin transaction use the same
            # isolated disposable database; no authentication dependency or
            # execution-context override is installed.
            from contextlib import asynccontextmanager
            from datetime import datetime, timedelta
            import jwt
            from fastapi import FastAPI
            from httpx import ASGITransport, AsyncClient
            from ai_karen_engine.api_routes.chat import runtime as pin_ingress
            from ai_karen_engine.auth import auth_middleware, auth_service as auth_facade
            from ai_karen_engine.auth.auth_middleware import SecureAuthMiddleware
            from ai_karen_engine.core.security.auth_config import auth_config
            from ai_karen_engine.database.models import AuthSession
            from ai_karen_engine.services.auth.auth_service import AuthService

            # The pin-specific disposable schema predates general AuthUser
            # fields. Extend only this throwaway fixture for canonical ORM
            # session validation; never migrate a shared application schema.
            await raw.execute("""
                ALTER TABLE public.auth_users
                    ADD COLUMN email varchar(255),
                    ADD COLUMN username varchar(255),
                    ADD COLUMN full_name varchar(255),
                    ADD COLUMN password_hash varchar(255),
                    ADD COLUMN tenant_id uuid REFERENCES public.tenants(id),
                    ADD COLUMN roles jsonb NOT NULL DEFAULT '[]'::jsonb,
                    ADD COLUMN preferences jsonb DEFAULT '{}'::jsonb,
                    ADD COLUMN is_verified boolean NOT NULL DEFAULT true,
                    ADD COLUMN is_active boolean NOT NULL DEFAULT true,
                    ADD COLUMN two_factor_enabled boolean NOT NULL DEFAULT false,
                    ADD COLUMN two_factor_secret varchar(32),
                    ADD COLUMN created_at timestamp NOT NULL DEFAULT now(),
                    ADD COLUMN updated_at timestamp NOT NULL DEFAULT now(),
                    ADD COLUMN last_login timestamp,
                    ADD COLUMN failed_login_attempts integer NOT NULL DEFAULT 0,
                    ADD COLUMN locked_until timestamp;
            """)
            await raw.execute("""
                UPDATE public.auth_users
                SET tenant_id=$1,
                    email=user_id::text || '@example.invalid',
                    username=user_id::text,
                    roles='["user"]'::jsonb
            """, tenant_b)
            async with engine.begin() as connection:
                await connection.run_sync(AuthSession.__table__.create)

            secret = "isolated-disposable-pin-session-test-secret"

            def signed_token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
                now = datetime.utcnow()
                return jwt.encode(
                    {
                        "sub": str(user_id),
                        "tenant_id": str(tenant_id),
                        # Stale client claims must never grant permissions.
                        "roles": ["admin"],
                        "permissions": ["pin:override"],
                        "iss": "ai-karen",
                        "aud": "ai-karen-users",
                        "iat": now,
                        "exp": now + timedelta(minutes=15),
                    },
                    secret,
                    algorithm="HS256",
                )

            owner_token = signed_token(owner_b, tenant_b)
            foreign_token = signed_token(owner_a, tenant_b)

            for actor, access_token in (
                (owner_b, owner_token),
                (owner_a, foreign_token),
            ):
                await raw.execute("""
                    INSERT INTO public.auth_sessions
                        (session_id, user_id, access_token, refresh_token,
                         expires_in, created_at, last_accessed, is_active)
                    VALUES ($1,$2,$3,$4,3600,now(),now(),true)
                """, uuid.uuid4(), actor, access_token, str(uuid.uuid4()))

            @asynccontextmanager
            async def auth_session_scope():
                async with maker() as session:
                    async with session.begin():
                        yield session

            auth_service = object.__new__(AuthService)
            auth_service._initialized = True
            auth_service._config = SimpleNamespace(
                jwt_secret_key=secret,
                jwt_algorithm="HS256",
            )
            auth_service._user_cache = {}
            auth_service._session_scope = auth_session_scope

            async def get_disposable_auth_service():
                return auth_service

            verifier = object.__new__(SecureAuthMiddleware)
            verifier.jwt_secret = secret
            verifier.jwt_algorithm = "HS256"
            # This is only the advisory Redis check. Durable PostgreSQL
            # AuthService.validate_session remains mandatory on every token.
            verifier._is_token_revoked = lambda token_id: False
            monkeypatch.setattr(
                auth_middleware, "get_auth_middleware", lambda: verifier
            )
            monkeypatch.setattr(
                auth_facade, "get_auth_service", get_disposable_auth_service
            )
            monkeypatch.setattr(auth_config, "should_bypass_auth", lambda: False)
            monkeypatch.setattr(
                pin_ingress,
                "get_runtime_settings",
                lambda: SimpleNamespace(
                    features=SimpleNamespace(
                        enable_ag_ui_bridge=True,
                        enable_ag_ui_durable_runs=True,
                        enable_presentation_pin_mutations=True,
                    )
                ),
            )

            http_pin = await create_owned_pin("runtime-http-mutation")
            http_key = str(uuid.uuid4())
            app = FastAPI()
            app.include_router(pin_ingress.router)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as http:
                mutation_url = "/chat/ag-ui/pins/mutations"
                body = {
                    "operation": "unpin",
                    "idempotency_key": http_key,
                    "pin_id": str(http_pin),
                }
                owner_headers = {"Authorization": f"Bearer {owner_token}"}
                foreign_headers = {"Authorization": f"Bearer {foreign_token}"}

                # Signed, active foreign identity still cannot modify a
                # same-tenant owner's pin or acquire its authoritative receipt.
                foreign = await http.post(
                    mutation_url,
                    json={**body, "idempotency_key": str(uuid.uuid4())},
                    headers=foreign_headers,
                )
                assert foreign.status_code == 200, foreign.text
                assert foreign.json()["receipt"]["outcome"] == "already_absent"
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, http_pin) == 1

                committed = await http.post(
                    mutation_url, json=body, headers=owner_headers
                )
                assert committed.status_code == 200, committed.text
                receipt = committed.json()["receipt"]
                assert committed.headers["cache-control"] == "private, no-store"
                assert committed.json()["committed"] is True
                assert receipt["outcome"] == "unpinned"
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, http_pin) == 0

                # Exact authenticated retry returns the original immutable
                # receipt after the pin row is gone.
                replay = await http.post(
                    mutation_url, json=body, headers=owner_headers
                )
                assert replay.status_code == 200
                assert replay.json()["receipt"] == receipt
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pin_mutation_receipts
                    WHERE tenant_id=$1 AND user_id=$2 AND idempotency_key=$3
                """, tenant_b, owner_b, uuid.UUID(http_key)) == 1

                changed = await http.post(
                    mutation_url,
                    json={**body, "pin_id": str(uuid.uuid4())},
                    headers=owner_headers,
                )
                assert changed.status_code == 409
                assert "committed" not in changed.text

                invalid = await http.post(
                    mutation_url,
                    json={**body, "position": 2},
                    headers=owner_headers,
                )
                assert invalid.status_code == 422

                # Compare-and-swap ordering is enforced through the same
                # authenticated HTTP and durable receipt path.
                reorder_pin = await create_owned_pin("runtime-http-reorder")
                reorder_key = str(uuid.uuid4())
                reorder_body = {
                    "operation": "reorder",
                    "idempotency_key": reorder_key,
                    "pin_id": str(reorder_pin),
                    "expected_revision": 1,
                    "position": 7,
                }
                reordered = await http.post(
                    mutation_url, json=reorder_body, headers=owner_headers
                )
                assert reordered.status_code == 200, reordered.text
                assert reordered.json()["receipt"]["committed_revision"] == 2
                ordered_row = await raw.fetchrow("""
                    SELECT position, revision FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, reorder_pin)
                assert ordered_row is not None
                assert ordered_row["position"] == 7
                assert ordered_row["revision"] == 2
                reordered_retry = await http.post(
                    mutation_url, json=reorder_body, headers=owner_headers
                )
                assert reordered_retry.status_code == 200
                assert reordered_retry.json()["receipt"] == reordered.json()["receipt"]
                stale = await http.post(
                    mutation_url,
                    json={**reorder_body, "idempotency_key": str(uuid.uuid4())},
                    headers=owner_headers,
                )
                assert stale.status_code == 409
                assert await raw.fetchval("""
                    SELECT revision FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, reorder_pin) == 2

                # Receipt insert failure must roll back the underlying DELETE
                # through the real HTTP route; a 503 can never mean committed.
                failed_pin = await create_owned_pin("runtime-http-receipt-failure")
                failed_key = uuid.uuid4()
                await raw.execute("""
                    CREATE FUNCTION public.reject_http_pin_receipt_insert()
                    RETURNS trigger LANGUAGE plpgsql AS $reject$
                    BEGIN
                      RAISE EXCEPTION 'disposable HTTP receipt insert failure';
                    END;
                    $reject$;
                    CREATE TRIGGER reject_http_pin_receipt_insert
                    BEFORE INSERT ON public.conversation_presentation_pin_mutation_receipts
                    FOR EACH ROW EXECUTE FUNCTION public.reject_http_pin_receipt_insert();
                """)
                try:
                    failed = await http.post(
                        mutation_url,
                        json={
                            "operation": "unpin",
                            "idempotency_key": str(failed_key),
                            "pin_id": str(failed_pin),
                        },
                        headers=owner_headers,
                    )
                    assert failed.status_code == 503, failed.text
                    assert "committed" not in failed.text
                    assert await raw.fetchval("""
                        SELECT count(*) FROM public.conversation_presentation_pins
                        WHERE pin_id=$1
                    """, failed_pin) == 1
                    assert await raw.fetchval("""
                        SELECT count(*) FROM public.conversation_presentation_pin_mutation_receipts
                        WHERE tenant_id=$1 AND user_id=$2 AND idempotency_key=$3
                    """, tenant_b, owner_b, failed_key) == 0
                finally:
                    await raw.execute("""
                        DROP TRIGGER IF EXISTS reject_http_pin_receipt_insert
                          ON public.conversation_presentation_pin_mutation_receipts;
                        DROP FUNCTION IF EXISTS public.reject_http_pin_receipt_insert();
                    """)

                # Revocation in the actual auth_sessions table must reject a
                # still-cryptographically-valid JWT before pin mutation.
                revoked_pin = await create_owned_pin("runtime-http-revoked")
                await raw.execute("""
                    UPDATE public.auth_sessions
                    SET is_active=false WHERE access_token=$1
                """, owner_token)
                revoked = await http.post(
                    mutation_url,
                    json={
                        **body,
                        "idempotency_key": str(uuid.uuid4()),
                        "pin_id": str(revoked_pin),
                    },
                    headers=owner_headers,
                )
                assert revoked.status_code == 401, revoked.text
                assert "committed" not in revoked.text
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, revoked_pin) == 1

                # A previously valid bearer token becomes unusable when the
                # durable user's tenant changes, even if the session is active.
                await raw.execute("""
                    UPDATE public.auth_sessions SET is_active=true
                    WHERE access_token=$1
                """, owner_token)
                await raw.execute("""
                    UPDATE public.auth_users SET tenant_id=$1 WHERE user_id=$2
                """, tenant_a, owner_b)
                drifted = await http.post(
                    mutation_url,
                    json={
                        "operation": "unpin",
                        "idempotency_key": str(uuid.uuid4()),
                        "pin_id": str(revoked_pin),
                    },
                    headers=owner_headers,
                )
                assert drifted.status_code == 401, drifted.text
                assert "committed" not in drifted.text
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, revoked_pin) == 1

            rollback_pin = await create_owned_pin("runtime-receipt-rollback")
            await raw.execute("""
                CREATE FUNCTION public.reject_pin_receipt_test_insert()
                RETURNS trigger LANGUAGE plpgsql AS $pin_reject$
                BEGIN
                  RAISE EXCEPTION 'disposable receipt insert rejected';
                END;
                $pin_reject$;
                CREATE TRIGGER reject_pin_receipt_test_insert
                BEFORE INSERT ON public.conversation_presentation_pin_mutation_receipts
                FOR EACH ROW EXECUTE FUNCTION public.reject_pin_receipt_test_insert();
            """)
            try:
                with pytest.raises(PresentationPinUnavailable):
                    await repository.mutate_with_receipt(
                        **unpin_args(rollback_pin, uuid.uuid4(), "failed")
                    )
                # SQLAlchemy's RLS-scoped transaction must have rolled back
                # the DELETE when the receipt INSERT raised.
                assert await raw.fetchval("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE pin_id=$1
                """, rollback_pin) == 1
            finally:
                await raw.execute("""
                    DROP TRIGGER IF EXISTS reject_pin_receipt_test_insert
                      ON public.conversation_presentation_pin_mutation_receipts;
                    DROP FUNCTION IF EXISTS public.reject_pin_receipt_test_insert();
                """)
        finally:
            await engine.dispose()
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
                    "auth_sessions", "auth_users", "tenants",
                ):
                    await raw.execute(f'DROP TABLE IF EXISTS public.{table} CASCADE')
                # PostgreSQL does not drop standalone trigger functions with tables.
                await raw.execute(
                    'DROP FUNCTION IF EXISTS public.prevent_presentation_pin_receipt_mutation()'
                )
        finally:
            await raw.close()
