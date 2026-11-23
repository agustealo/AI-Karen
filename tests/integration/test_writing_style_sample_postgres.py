"""Disposable PostgreSQL proof: generic sample provenance and revocation.

The mocked source is a generic message. Real document consent is separately
proven against the canonical file table and receipt in the document test.
Only runs against the dedicated /karen_writing_style_test database; always
uses the non-superuser test role for RLS and backend sample mutations.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import AsyncMock

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest, KariSignatureResolver,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
)
from ai_karen_engine.services.formatting.karisignature_sample_analysis import (
    KariSignatureSample,
)
from ai_karen_engine.services.formatting.karisignature_persisted_sample_authority import (
    WritingStylePersistedSampleAuthority,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource, WritingStyleSampleProvenance,
)

pytestmark = pytest.mark.asyncio


async def test_postgres_source_consent_principal_rls_and_revocation():
    dsn = os.getenv("WRITING_STYLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated writing style PostgreSQL test database not configured")
    if urlparse(dsn).path != "/karen_writing_style_test":
        pytest.fail("Refuse non-disposable PostgreSQL database")

    raw = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    owner, delegate = uuid.uuid4(), uuid.uuid4()
    profile, source, sample, author, receipt = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    role = "style_sample_test_" + uuid.uuid4().hex[:12]
    engine = None
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
        root = Path(__file__).resolve().parents[2] / "supabase/migrations"
        for file in (
            "20261120235900_60_writing_style_identity.sql",
            "20261122010001_61_writing_style_sample_evidence.sql",
            "20261122010002_62_writing_style_document_author_consent.sql",
            "20261123030000_69_writing_style_document_file_tenant_text.sql",
            "20261123040000_70_writing_style_document_delegated_use_fence.sql",
        ):
            await raw.execute((root / file).read_text(encoding="utf-8"))
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2) ON CONFLICT DO NOTHING",
            tenant, other_tenant,
        )
        await raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.writing_style_profiles, '
            f'public.writing_style_revisions, public.writing_style_grants, '
            f'public.writing_style_sample_evidence, '
            f'public.writing_style_document_consents TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT ON public.files TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT, INSERT ON public.writing_style_audit, '
            f'public.writing_style_sample_audit TO "{role}"'
        )
        await raw.execute(
            f'GRANT USAGE ON SEQUENCE public.writing_style_audit_id_seq, '
            f'public.writing_style_sample_audit_id_seq TO "{role}"'
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

        client_factory = lambda: TestClient()
        identities = WritingStyleProfileRepository(client_factory)
        await identities.create_draft(
            tenant_id=str(tenant), owner_actor_id=str(owner),
            profile_id=str(profile), kind="personal", label="Sample-backed",
            correlation_id="create-sample-test",
        )
        data = {
            "tenant_id": str(tenant), "actor_id": str(owner),
            "profile_id": str(profile), "sample_id": str(sample),
            "source_type": "message", "source_id": str(source),
            "correlation_id": "register-sample-test",
        }
        authority = type("Authority", (), {"verify_analysis": AsyncMock()})()
        authority.verify_analysis.return_value = VerifiedWritingStyleSource(
            tenant_id=str(tenant), profile_id=str(profile), owner_actor_id=str(owner),
            source_id=str(source), source_type="message", author_actor_id=str(author),
            consent_receipt_id=str(receipt), analysis_allowed=True,
            style_use_allowed=False,
            consent_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        provenance = WritingStyleSampleProvenance(
            authority=authority, client_factory=client_factory,
        )
        await provenance.register(**data)

        async def visible(actor, tenant_scope):
            async with TestClient().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, str(tenant_scope), str(actor)
                )
                result = await session.execute(
                    text("SELECT sample_id FROM public.writing_style_sample_evidence")
                )
                return result.scalars().all()

        assert await visible(owner, tenant) == [sample]
        assert await visible(delegate, tenant) == []
        assert await visible(owner, other_tenant) == []

        expression = {"tone": "direct", "register": "professional"}
        # Analysis permission alone cannot authorize a published style derived
        # from a sample, even for a direct SQL actor.
        with pytest.raises(Exception, match="source use consent unavailable"):
            await identities.publish(
                tenant_id=str(tenant), actor_id=str(owner),
                profile_id=str(profile), revision_id=str(uuid.uuid4()),
                approved_expression=expression, expected_revision=0,
                correlation_id="publish-without-use-consent",
            )

        # A current consent must be re-verified through the canonical source
        # owner for a NEW sample. Already registered evidence is immutable:
        # permission escalation by UPDATE is forbidden.
        with pytest.raises(Exception, match="immutable"):
            async with TestClient().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, str(tenant), str(owner)
                )
                await session.execute(
                    text(
                        "UPDATE public.writing_style_sample_evidence "
                        "SET style_use_allowed=true WHERE sample_id=CAST(:id AS uuid)"
                    ),
                    {"id": str(sample)},
                )

        # Revocation is one-way, auditable and does not leak sample content.
        assert await provenance.revoke(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(profile), sample_id=str(sample),
            correlation_id="revoke-sample-test",
        )
        assert not await provenance.revoke(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(profile), sample_id=str(sample),
            correlation_id="repeat-revoke",
        )
        async with TestClient().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, str(tenant), str(owner)
            )
            recorded = await session.execute(
                text(
                    "SELECT action FROM public.writing_style_sample_audit "
                    "ORDER BY id"
                ),
            )
            assert [row[0] for row in recorded.fetchall()] == ["register", "revoke"]

        # Consent-approved evidence may be used in a published style. Revoking
        # that evidence must atomically revoke its parent profile and grants.
        live_profile, live_source, live_sample = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await identities.create_draft(
            tenant_id=str(tenant), owner_actor_id=str(owner),
            profile_id=str(live_profile), kind="client", label="Consented client style",
            correlation_id="create-consented-profile",
        )
        authority.verify_analysis.return_value = VerifiedWritingStyleSource(
            tenant_id=str(tenant), profile_id=str(live_profile),
            owner_actor_id=str(owner), source_id=str(live_source),
            source_type="message", author_actor_id=str(author),
            consent_receipt_id=str(uuid.uuid4()), analysis_allowed=True,
            style_use_allowed=True,
            consent_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        await provenance.register(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), sample_id=str(live_sample),
            source_type="message", source_id=str(live_source),
            correlation_id="consented-sample",
        )
        # WS-02C: evidence record alone is insufficient. Current author/receipt
        # and the exact text must come from the canonical live source owner.
        sample_body = " ".join(
            ["A real source owner must verify these writing samples"] * 5
        )
        current_sample = KariSignatureSample(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), sample_id=str(live_sample),
            source_ref=f"message:{live_source}", content=sample_body,
            digest=KariSignatureSample.content_digest(sample_body),
        )
        source_reader = type(
            "ContentOwner", (),
            {"read_current_content": AsyncMock(return_value=sample_body)}
        )()
        sample_gate = WritingStylePersistedSampleAuthority(
            source_authority=authority, content_reader=source_reader,
            client_factory=client_factory,
        )
        analysis_request = KariSignatureRequest(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), purpose="analyze_style",
            correlation_id="live-source-analysis-proof",
        )
        assert await sample_gate.authorize_analysis(
            request=analysis_request, sample=current_sample
        )
        source_reader.read_current_content.return_value = sample_body + " drift"
        assert not await sample_gate.authorize_analysis(
            request=analysis_request, sample=current_sample
        )
        source_reader.read_current_content.return_value = sample_body

        published = await identities.publish(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), revision_id=str(uuid.uuid4()),
            approved_expression=expression, expected_revision=0,
            correlation_id="consented-publish",
        )
        assert published.revision_number == 1
        # Published profiles cannot accept further sample-analysis changes.
        assert not await sample_gate.authorize_analysis(
            request=analysis_request, sample=current_sample
        )
        await identities.grant_use(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="consented-grant",
        )
        # Direct SQL owners must not grant beyond the consent expiry,
        # even when bypassing the repository's grant_use helper.
        async with TestClient().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, str(tenant), str(owner)
            )
            await session.execute(
                text(
                    "UPDATE public.writing_style_grants SET expires_at=NULL "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) "
                    "AND actor_id=CAST(:actor AS uuid)"
                ),
                {"tenant": str(tenant), "profile": str(live_profile),
                 "actor": str(delegate)},
            )
            await session.execute(
                text(
                    "INSERT INTO public.writing_style_grants "
                    "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,"
                    "granted_by,expires_at) VALUES "
                    "(CAST(:tenant AS uuid),CAST(:profile AS uuid),"
                    "CAST(:owner AS uuid),CAST(:delegate AS uuid),"
                    "'draft_social',CAST(:owner AS uuid),NULL)"
                ),
                {"tenant": str(tenant), "profile": str(live_profile),
                 "owner": str(owner), "delegate": str(delegate)},
            )
            result = await session.execute(
                text(
                    "SELECT purpose,expires_at FROM public.writing_style_grants "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) "
                    "AND actor_id=CAST(:delegate AS uuid) "
                    "ORDER BY purpose"
                ),
                {"tenant": str(tenant), "profile": str(live_profile),
                 "delegate": str(delegate)},
            )
            capped = result.fetchall()
            assert [row[0] for row in capped] == ["draft_email", "draft_social"]
            assert all(
                row[1] == authority.verify_analysis.return_value.consent_expires_at
                for row in capped
            )
        # A previous publication is irreversible, even when a SQL owner
        # attempts to rewrite both lifecycle and revision counters at once.
        for statement in (
            "UPDATE public.writing_style_profiles SET state='draft' "
            "WHERE tenant_id=CAST(:tenant AS uuid) "
            "AND profile_id=CAST(:profile AS uuid)",
            "UPDATE public.writing_style_profiles SET state='draft', "
            "publication_revision=0, current_revision_id=NULL "
            "WHERE tenant_id=CAST(:tenant AS uuid) "
            "AND profile_id=CAST(:profile AS uuid)",
        ):
            with pytest.raises(Exception, match="lifecycle violation"):
                async with TestClient().get_async_session() as session:
                    await WritingStyleProfileRepository._scope(
                        session, str(tenant), str(owner)
                    )
                    await session.execute(
                        text(statement),
                        {"tenant": str(tenant), "profile": str(live_profile)},
                    )
        async with TestClient().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, str(tenant), str(owner)
            )
            state = await session.execute(
                text(
                    "SELECT state,publication_revision "
                    "FROM public.writing_style_profiles "
                    "WHERE profile_id=CAST(:profile AS uuid)"
                ),
                {"profile": str(live_profile)},
            )
            assert state.one() == ("published", 1)
        # Direct SQL must not attach evidence after publication and thereby
        # invalidate existing delegate grant consent without recapping grants.
        with pytest.raises(Exception, match="requires a draft profile"):
            async with TestClient().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, str(tenant), str(owner)
                )
                await session.execute(
                    text(
                        "INSERT INTO public.writing_style_sample_evidence "
                        "(tenant_id,profile_id,owner_actor_id,sample_id,source_type,"
                        "source_id,source_author_id,consent_receipt_id,"
                        "analysis_allowed,style_use_allowed,consent_expires_at) "
                        "VALUES (CAST(:tenant AS uuid),CAST(:profile AS uuid),"
                        "CAST(:owner AS uuid),CAST(:sample AS uuid),'message',"
                        "CAST(:source AS uuid),CAST(:author AS uuid),"
                        "CAST(:receipt AS uuid),true,true,"
                        "clock_timestamp()+interval '10 seconds')"
                    ),
                    {
                        "tenant": str(tenant), "profile": str(live_profile),
                        "owner": str(owner), "sample": str(uuid.uuid4()),
                        "source": str(uuid.uuid4()), "author": str(author),
                        "receipt": str(uuid.uuid4()),
                    },
                )
        live_request = KariSignatureRequest(
            tenant_id=str(tenant), actor_id=str(delegate),
            profile_id=str(live_profile), purpose="draft_email",
            correlation_id="consented-resolve",
        )
        assert (await KariSignatureResolver(identities).resolve(live_request)).presentation == expression
        # Direct owner SQL must fence the published profile without calling
        # the Python revoke wrapper. Delegates cannot read sample evidence,
        # so a delegate-side NOT EXISTS predicate alone cannot be trusted.
        async with TestClient().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, str(tenant), str(owner)
            )
            changed = await session.execute(
                text(
                    "UPDATE public.writing_style_sample_evidence "
                    "SET revoked_at=clock_timestamp() "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) "
                    "AND sample_id=CAST(:sample AS uuid) "
                    "AND revoked_at IS NULL RETURNING sample_id"
                ),
                {
                    "tenant": str(tenant), "profile": str(live_profile),
                    "sample": str(live_sample),
                },
            )
            assert changed.scalar_one() == live_sample
        with pytest.raises(PermissionError, match="style_unavailable"):
            await KariSignatureResolver(identities).resolve(live_request)
        assert not await provenance.revoke(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(live_profile), sample_id=str(live_sample),
            correlation_id="already-revoked-direct-sql",
        )
        async with TestClient().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, str(tenant), str(owner)
            )
            result = await session.execute(
                text(
                    "SELECT state FROM public.writing_style_profiles "
                    "WHERE profile_id=CAST(:profile AS uuid)"
                ),
                {"profile": str(live_profile)},
            )
            assert result.scalar_one() == "revoked"
            result = await session.execute(
                text(
                    "SELECT count(*) FROM public.writing_style_grants "
                    "WHERE profile_id=CAST(:profile AS uuid) "
                    "AND revoked_at IS NULL"
                ),
                {"profile": str(live_profile)},
            )
            assert result.scalar_one() == 0
            result = await session.execute(
                text(
                    "SELECT count(*) FROM public.writing_style_audit "
                    "WHERE profile_id=CAST(:profile AS uuid) "
                    "AND action='revoke_profile'"
                ),
                {"profile": str(live_profile)},
            )
            assert result.scalar_one() == 1

        # A grant UPDATE has already locked its row. It must not then acquire
        # the profile lock in reverse order while concurrent revocation holds
        # profile first and waits for its grants.
        race_profile = uuid.uuid4()
        await identities.create_draft(
            tenant_id=str(tenant), owner_actor_id=str(owner),
            profile_id=str(race_profile), kind="personal",
            label="Grant lock order", correlation_id="lock-order-create",
        )
        await identities.publish(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(race_profile), revision_id=str(uuid.uuid4()),
            approved_expression=expression, expected_revision=0,
            correlation_id="lock-order-publish",
        )
        await identities.grant_use(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(race_profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="lock-order-grant",
        )
        grant_updated = asyncio.Event()
        allow_commit = asyncio.Event()

        async def grant_update_first():
            async with TestClient().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, str(tenant), str(owner)
                )
                await session.execute(
                    text(
                        "UPDATE public.writing_style_grants SET expires_at=NULL "
                        "WHERE tenant_id=CAST(:tenant AS uuid) "
                        "AND profile_id=CAST(:profile AS uuid) "
                        "AND actor_id=CAST(:delegate AS uuid)"
                    ),
                    {
                        "tenant": str(tenant), "profile": str(race_profile),
                        "delegate": str(delegate),
                    },
                )
                grant_updated.set()
                await allow_commit.wait()

        async def profile_revocation_second():
            await grant_updated.wait()
            revoking = asyncio.create_task(identities.revoke_profile(
                tenant_id=str(tenant), actor_id=str(owner),
                profile_id=str(race_profile), correlation_id="lock-order-revoke",
            ))
            await asyncio.sleep(0.15)
            allow_commit.set()
            return await revoking

        try:
            updated, revoked = await asyncio.wait_for(
                asyncio.gather(grant_update_first(), profile_revocation_second()),
                timeout=8,
            )
        finally:
            allow_commit.set()
        assert revoked is True
        with pytest.raises(PermissionError, match="style_unavailable"):
            await KariSignatureResolver(identities).resolve(
                KariSignatureRequest(
                    tenant_id=str(tenant), actor_id=str(delegate),
                    profile_id=str(race_profile), purpose="draft_email",
                    correlation_id="lock-order-denied",
                )
            )

        # Force the original deadlock interleaving: direct SQL locks the
        # evidence row before its UPDATE trigger needs the profile, while
        # the repository attempts revocation of the same sample. Repository
        # must not hold the parent lock while waiting on that evidence row.
        race_sample_profile = uuid.uuid4()
        race_sample_id = uuid.uuid4()
        race_source_id = uuid.uuid4()
        await identities.create_draft(
            tenant_id=str(tenant), owner_actor_id=str(owner),
            profile_id=str(race_sample_profile), kind="client",
            label="Concurrent sample revoke", correlation_id="sample-race-create",
        )
        authority.verify_analysis.return_value = VerifiedWritingStyleSource(
            tenant_id=str(tenant), profile_id=str(race_sample_profile),
            owner_actor_id=str(owner), source_id=str(race_source_id),
            source_type="message", author_actor_id=str(author),
            consent_receipt_id=str(uuid.uuid4()), analysis_allowed=True,
            style_use_allowed=True,
            consent_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        await provenance.register(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(race_sample_profile), sample_id=str(race_sample_id),
            source_type="message", source_id=str(race_source_id),
            correlation_id="sample-race-register",
        )
        await identities.publish(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(race_sample_profile), revision_id=str(uuid.uuid4()),
            approved_expression=expression, expected_revision=0,
            correlation_id="sample-race-publish",
        )
        await identities.grant_use(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(race_sample_profile), grantee_actor_id=str(delegate),
            purpose="draft_email", correlation_id="sample-race-grant",
        )
        sample_locked = asyncio.Event()
        begin_sql_update = asyncio.Event()

        async def direct_sample_revoke():
            async with TestClient().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, str(tenant), str(owner)
                )
                await session.execute(
                    text(
                        "SELECT sample_id FROM public.writing_style_sample_evidence "
                        "WHERE profile_id=CAST(:profile AS uuid) "
                        "AND sample_id=CAST(:sample AS uuid) FOR UPDATE"
                    ),
                    {"profile": str(race_sample_profile), "sample": str(race_sample_id)},
                )
                sample_locked.set()
                await begin_sql_update.wait()
                changed = await session.execute(
                    text(
                        "UPDATE public.writing_style_sample_evidence "
                        "SET revoked_at=clock_timestamp() "
                        "WHERE profile_id=CAST(:profile AS uuid) "
                        "AND sample_id=CAST(:sample AS uuid) "
                        "AND revoked_at IS NULL RETURNING sample_id"
                    ),
                    {"profile": str(race_sample_profile), "sample": str(race_sample_id)},
                )
                return changed.scalar_one() == race_sample_id

        async def repository_revoke_concurrently():
            await sample_locked.wait()
            task = asyncio.create_task(provenance.revoke(
                tenant_id=str(tenant), actor_id=str(owner),
                profile_id=str(race_sample_profile), sample_id=str(race_sample_id),
                correlation_id="sample-race-wrapper",
            ))
            await asyncio.sleep(0.15)
            begin_sql_update.set()
            return await task

        try:
            direct_changed, wrapper_changed = await asyncio.wait_for(
                asyncio.gather(
                    direct_sample_revoke(), repository_revoke_concurrently()
                ),
                timeout=8,
            )
        finally:
            begin_sql_update.set()
        assert direct_changed is True
        assert wrapper_changed is False
        with pytest.raises(PermissionError, match="style_unavailable"):
            await KariSignatureResolver(identities).resolve(
                KariSignatureRequest(
                    tenant_id=str(tenant), actor_id=str(delegate),
                    profile_id=str(race_sample_profile), purpose="draft_email",
                    correlation_id="sample-race-denied",
                )
            )

        # A source-revoked profile is never a path to style application.
        with pytest.raises(PermissionError):
            await KariSignatureResolver(identities).resolve(
                KariSignatureRequest(
                    tenant_id=str(tenant), actor_id=str(delegate),
                    profile_id=str(profile), purpose="draft_email",
                    correlation_id="no-style-use",
                )
            )
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            await raw.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"')
            await raw.execute(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"')
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await raw.close()
