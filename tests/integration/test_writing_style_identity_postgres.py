"""Real PostgreSQL proof for WS-02 identity publication and purpose-scoped use.

Runs only against a disposable /karen_writing_style_test database. The tests
never create or mutate production data. A non-superuser role exercises FORCE RLS.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureResolver,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
    WritingStyleRevisionConflict,
)

pytestmark = pytest.mark.asyncio


async def test_writing_style_publish_grant_isolation_revocation_and_atomicity():
    dsn = os.environ.get("WRITING_STYLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated Writing Studio test database is not configured")
    if urlparse(dsn).path != "/karen_writing_style_test":
        pytest.fail("WRITING_STYLE_TEST_DATABASE_URL must target /karen_writing_style_test")

    raw_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    raw = await asyncpg.connect(raw_dsn)
    role = "writing_style_test_" + uuid.uuid4().hex[:12]
    engine = None

    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    owner, delegate, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    profile, revision_id = uuid.uuid4(), uuid.uuid4()
    try:
        await raw.execute("""
            DROP TABLE IF EXISTS public.writing_style_document_consents CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_evidence CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_sample_revoke_only() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_sample_revoke_fence() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_bound_grant_to_source_consent() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_require_draft_sample() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_enforce_profile_lifecycle() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_require_source_use_consent() CASCADE;
            DROP TABLE IF EXISTS public.writing_style_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_grants CASCADE;
            DROP TABLE IF EXISTS public.writing_style_revisions CASCADE;
            DROP TABLE IF EXISTS public.writing_style_profiles CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_prevent_revision_mutation() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_document_consent_validate() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_document_consent_revoke_fence() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_document_use_expiry(uuid,uuid,uuid) CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_revoke_consent_on_file_change() CASCADE;
            DROP FUNCTION IF EXISTS kari_internal.writing_style_authorized_document_sources(uuid,uuid,uuid,text,uuid,bigint,text) CASCADE;
            DROP TABLE IF EXISTS public.files CASCADE;
            CREATE TABLE IF NOT EXISTS public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.files (
                file_id text PRIMARY KEY,
                tenant_id uuid NOT NULL,
                owner_user_id uuid NOT NULL,
                name text NOT NULL,
                mime_type text NOT NULL,
                bytes bigint NOT NULL,
                sha256 text,
                storage_uri text,
                deleted_at timestamptz
            );
        """)
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261120235900_60_writing_style_identity.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        sample_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261122010001_61_writing_style_sample_evidence.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(sample_migration)
        await raw.execute((
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261122010002_62_writing_style_document_author_consent.sql"
        ).read_text(encoding="utf-8"))
        await raw.execute((
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261123030000_69_writing_style_document_file_tenant_text.sql"
        ).read_text(encoding="utf-8"))
        await raw.execute((
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261123040000_70_writing_style_document_delegated_use_fence.sql"
        ).read_text(encoding="utf-8"))
        await raw.execute((
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261123060000_72_writing_style_delegated_storage_integrity.sql"
        ).read_text(encoding="utf-8"))
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2) ON CONFLICT DO NOTHING",
            tenant_a, tenant_b,
        )
        await raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        await raw.execute(f'GRANT USAGE ON SCHEMA kari_internal TO "{role}"')
        await raw.execute(
            f'GRANT EXECUTE ON FUNCTION '
            f'kari_internal.writing_style_authorized_document_sources('
            f'uuid,uuid,uuid,text,uuid,bigint,text) TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.writing_style_profiles, '
            f'public.writing_style_revisions, public.writing_style_grants TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT, INSERT ON public.writing_style_audit TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT ON public.writing_style_sample_evidence, '
            f'public.writing_style_document_consents, public.files TO "{role}"'
        )
        await raw.execute(
            f'GRANT USAGE ON SEQUENCE public.writing_style_audit_id_seq TO "{role}"'
        )
        engine = create_async_engine(
            dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_size=4, max_overflow=0,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        class TestClient:
            @asynccontextmanager
            async def get_async_session(self):
                async with sessions() as session:
                    async with session.begin():
                        await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                        yield session

        repo = WritingStyleProfileRepository(lambda: TestClient())
        params = {
            "tenant_id": str(tenant_a),
            "owner_actor_id": str(owner),
            "profile_id": str(profile),
            "kind": "client",
            "label": "Client writing identity",
            "correlation_id": "ws02-integration",
        }
        await repo.create_draft(**params)
        expression = {
            "style": "analytical", "tone": "direct",
            "register": "professional", "verbosity": "detailed",
            "language_style": "en-us",
        }
        saved = await repo.publish(
            tenant_id=str(tenant_a), actor_id=str(owner),
            profile_id=str(profile), revision_id=str(revision_id),
            approved_expression=expression, expected_revision=0,
            correlation_id="publish-a",
        )
        assert saved.revision_number == 1
        assert await repo.read_current_published(
            request=KariSignatureRequest(
                tenant_id=str(tenant_b), actor_id=str(delegate),
                profile_id=str(profile), purpose="draft_email",
                correlation_id="deny-tenant-b",
            )
        ) is None

        await repo.grant_use(
            tenant_id=str(tenant_a), actor_id=str(owner),
            profile_id=str(profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="grant-a",
        )
        request = KariSignatureRequest(
            tenant_id=str(tenant_a), actor_id=str(delegate),
            profile_id=str(profile), purpose="draft_email",
            correlation_id="resolve-a",
        )
        resolver = KariSignatureResolver(repo)
        assert (await resolver.resolve(request)).presentation == expression

        assert not await repo.authorize_use(
            request=KariSignatureRequest(
                tenant_id=str(tenant_a), actor_id=str(stranger),
                profile_id=str(profile), purpose="draft_email",
                correlation_id="resolve-stranger",
            ),
            revision=saved,
        )
        assert not await repo.authorize_use(
            request=KariSignatureRequest(
                tenant_id=str(tenant_a), actor_id=str(delegate),
                profile_id=str(profile), purpose="publish_social",
                correlation_id="resolve-wrong-purpose",
            ),
            revision=saved,
        )

        # A delegated identity can be revoked without revoking other purposes.
        assert await repo.revoke_grant(
            tenant_id=str(tenant_a), actor_id=str(owner),
            profile_id=str(profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="revoke-grant",
        )
        with pytest.raises(PermissionError, match="style_unavailable"):
            await resolver.resolve(request)
        await repo.grant_use(
            tenant_id=str(tenant_a), actor_id=str(owner),
            profile_id=str(profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="regrant-a",
        )
        assert (await resolver.resolve(request)).revision_number == 1

        # Real FORCE RLS checks both tenant and principal, including direct
        # SQL that bypasses the repository's WHERE clauses.
        async def direct_visible(*, current_tenant, current_actor, purpose):
            async with TestClient().get_async_session() as session:
                for setting, value in (
                    ("app.current_tenant_id", str(current_tenant)),
                    ("app.current_user_id", str(current_actor)),
                    ("app.current_style_purpose", purpose),
                ):
                    await session.execute(
                        text("SELECT set_config(:setting, :value, true)"),
                        {"setting": setting, "value": value},
                    )
                counts = []
                for table in (
                    "writing_style_profiles", "writing_style_revisions",
                    "writing_style_grants", "writing_style_audit",
                ):
                    result = await session.execute(
                        text(f"SELECT count(*) FROM public.{table}")
                    )
                    counts.append(int(result.scalar_one()))
                return counts

        assert await direct_visible(
            current_tenant=tenant_b, current_actor=delegate,
            purpose="draft_email",
        ) == [0, 0, 0, 0]
        assert await direct_visible(
            current_tenant=tenant_a, current_actor=stranger,
            purpose="draft_email",
        ) == [0, 0, 0, 0]
        assert await direct_visible(
            current_tenant=tenant_a, current_actor=delegate,
            purpose="publish_social",
        ) == [0, 0, 1, 0]
        assert (await direct_visible(
            current_tenant=tenant_a, current_actor=delegate,
            purpose="draft_email",
        ))[:2] == [1, 1]

        # A forged actor UUID supplied directly to a SQL mutation cannot
        # bypass the authenticated principal's RLS context.
        async with TestClient().get_async_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_a)},
            )
            await session.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(stranger)},
            )
            changed = await session.execute(
                text(
                    "UPDATE public.writing_style_profiles SET label='forged' "
                    "WHERE profile_id=CAST(:profile AS uuid) "
                    "AND owner_actor_id=CAST(:owner AS uuid) RETURNING profile_id"
                ),
                {"profile": str(profile), "owner": str(owner)},
            )
            assert changed.first() is None

        # Concurrent writes from revision 1 have exactly one winner.
        async def publish_again(index: int):
            return await repo.publish(
                tenant_id=str(tenant_a), actor_id=str(owner),
                profile_id=str(profile), revision_id=str(uuid.uuid4()),
                approved_expression=expression, expected_revision=1,
                correlation_id=f"publish-race-{index}",
            )

        results = await asyncio.gather(
            publish_again(1), publish_again(2), return_exceptions=True
        )
        assert len([item for item in results if hasattr(item, "revision_number")]) == 1
        assert len([
            item for item in results if isinstance(item, WritingStyleRevisionConflict)
        ]) == 1

        assert await repo.revoke_profile(
            tenant_id=str(tenant_a), actor_id=str(owner),
            profile_id=str(profile), correlation_id="revoke-a",
        )
        with pytest.raises(PermissionError, match="style_unavailable"):
            await resolver.resolve(request)

        # FORCE RLS prevents even an authenticated owner from directly
        # editing a published revision. Ordinary UPDATE affects zero rows.
        async with TestClient().get_async_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_a)},
            )
            await session.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(owner)},
            )
            untouched = await session.execute(
                text(
                    "UPDATE public.writing_style_revisions SET "
                    "approved_expression='{}'::jsonb WHERE "
                    "tenant_id=CAST(:tenant AS uuid) AND "
                    "profile_id=CAST(:profile AS uuid) RETURNING revision_id"
                ),
                {"tenant": str(tenant_a), "profile": str(profile)},
            )
            assert untouched.first() is None

        # A privileged direct UPDATE bypasses RLS but must still be blocked
        # by the immutable-revision trigger. Run it in its own statement.
        with pytest.raises(Exception, match="immutable"):
            await raw.execute(
                "UPDATE public.writing_style_revisions SET "
                "approved_expression='{}'::jsonb "
                "WHERE tenant_id=$1 AND profile_id=$2",
                tenant_a, profile,
            )
        # Check that mutation and audit are committed together, not that
        # an audit-only record can be fabricated.
        async with TestClient().get_async_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_a)},
            )
            await session.execute(
                text("SELECT set_config('app.current_user_id', :u, true)"),
                {"u": str(owner)},
            )
            result = await session.execute(
                text(
                    "SELECT action, publication_revision FROM public.writing_style_audit "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) ORDER BY id"
                ),
                {"tenant": str(tenant_a), "profile": str(profile)},
            )
            events = result.fetchall()
        assert [item[0] for item in events] == [
            "create", "publish", "grant", "revoke_grant", "grant",
            "publish", "revoke_profile",
        ]

        # Governed tenant erasure must delete immutable child revisions and
        # grants without allowing a direct revision edit or deletion.
        await raw.execute("DELETE FROM public.tenants WHERE id=$1", tenant_a)
        for table in (
            "writing_style_profiles", "writing_style_revisions",
            "writing_style_grants", "writing_style_audit",
        ):
            remaining = await raw.fetchval(
                f"SELECT count(*) FROM public.{table} WHERE tenant_id=$1",
                tenant_a,
            )
            assert remaining == 0, table
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            await raw.execute(
                f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"'
            )
            await raw.execute(
                f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"'
            )
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await raw.close()


async def test_writing_style_input_rejects_noncanonical_identity_and_unbounded_fields():
    repo = WritingStyleProfileRepository(lambda: None)

    with pytest.raises(ValueError, match="invalid_style_identifier"):
        await repo.create_draft(
            tenant_id="not-a-uuid", owner_actor_id=str(uuid.uuid4()),
            profile_id=str(uuid.uuid4()), kind="personal",
            label="Test", correlation_id="corr",
        )
    with pytest.raises(ValueError, match="invalid_style_profile"):
        await repo.create_draft(
            tenant_id=str(uuid.uuid4()), owner_actor_id=str(uuid.uuid4()),
            profile_id=str(uuid.uuid4()), kind="system",
            label="Test", correlation_id="corr",
        )
