"""WS-04A9B: real disposable PostgreSQL author-consent ledger acceptance.

Runs after the canonical WS-02 tests in the existing /karen_writing_style_test
database. Never accesses production databases, Supabase Storage, or source bytes.
This does NOT verify authorship outside authenticated first-party attestation.
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
)
from ai_karen_engine.services.postgres_document_style_consent_issuer import (
    PostgresDocumentStyleConsentIssuer,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleAccessDenied,
    WritingStyleProfileRepository,
)

pytestmark = pytest.mark.asyncio


async def test_first_party_author_consent_postgres() -> None:
    dsn = os.getenv("WRITING_STYLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated writing-style disposable PostgreSQL not configured")
    if urlparse(dsn).path != "/karen_writing_style_test":
        pytest.fail("Refuse to run against a non-disposable database")

    engine = None
    raw = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    tenant, foreign_tenant = uuid.uuid4(), uuid.uuid4()
    owner, other_actor = uuid.uuid4(), uuid.uuid4()
    profile, artifact, receipt = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    digest = "a" * 64
    role = "style_consent_test_" + uuid.uuid4().hex[:12]
    root = Path(__file__).resolve().parents[2] / "supabase/migrations"

    async def scoped(actor: uuid.UUID, scope: uuid.UUID, statement: str, *args):
        async with raw.transaction():
            await raw.execute(f'SET LOCAL ROLE "{role}"')
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(scope),
            )
            await raw.execute(
                "SELECT set_config('app.current_user_id', $1, true)",
                str(actor),
            )
            return await raw.execute(statement, *args)

    try:
        # This test owns the disposable database only. A fresh empty DB is
        # supplied by the existing KariSignature PostgreSQL CI job.
        await raw.execute("""
            DROP TABLE IF EXISTS public.runtime_approval_requests CASCADE;
            DROP TABLE IF EXISTS public.writing_style_document_consents CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_evidence CASCADE;
            DROP TABLE IF EXISTS public.writing_style_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_grants CASCADE;
            DROP TABLE IF EXISTS public.writing_style_revisions CASCADE;
            DROP TABLE IF EXISTS public.writing_style_profiles CASCADE;
            DROP TABLE IF EXISTS public.files CASCADE;
            DROP TABLE IF EXISTS public.auth_users CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_sample_revoke_only() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_sample_revoke_fence() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_bound_grant_to_source_consent() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_require_draft_sample() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_enforce_profile_lifecycle() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_require_source_use_consent() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_prevent_revision_mutation() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_document_consent_validate() CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_document_consent_revoke_fence() CASCADE;
            CREATE TABLE IF NOT EXISTS public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (user_id uuid PRIMARY KEY);
            CREATE TABLE public.files (
                file_id text PRIMARY KEY,
                tenant_id uuid NOT NULL,
                owner_user_id uuid NOT NULL,
                name text NOT NULL,
                mime_type text NOT NULL,
                bytes bigint NOT NULL,
                sha256 text,
                deleted_at timestamptz
            );
        """)
        for filename in (
            "20261006030000_26_runtime_human_approval_authority.sql",
            "20261120235900_60_writing_style_identity.sql",
            "20261122010001_61_writing_style_sample_evidence.sql",
            "20261122010002_62_writing_style_document_author_consent.sql",
        ):
            await raw.execute((root / filename).read_text(encoding="utf-8"))

        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2) "
            "ON CONFLICT DO NOTHING", tenant, foreign_tenant,
        )
        await raw.execute(
            "INSERT INTO public.auth_users (user_id) VALUES ($1),($2)",
            owner, other_actor,
        )
        await raw.execute(
            "INSERT INTO public.writing_style_profiles "
            "(tenant_id, profile_id, owner_actor_id, kind, label) "
            "VALUES ($1,$2,$3,'personal','Author controlled')",
            tenant, profile, owner,
        )
        await raw.execute(
            "INSERT INTO public.files "
            "(file_id, tenant_id, owner_user_id, name, mime_type, bytes, sha256) "
            "VALUES ($1,$2,$3,'author.txt','text/plain',10,$4)",
            str(artifact), tenant, owner, digest,
        )
        await raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE '
            f'ON public.writing_style_document_consents TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT, UPDATE ON public.runtime_approval_requests '
            f'TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT ON public.files, public.writing_style_profiles '
            f'TO "{role}"'
        )
        # PostgreSQL row-locking SELECT ... FOR SHARE requires the test
        # principal to possess UPDATE privilege on the locked relation.
        # This grant is restricted to the fresh disposable CI role/database;
        # the migration does not grant file mutation rights to application
        # clients or authenticated/anon roles.
        await raw.execute(
            f'GRANT UPDATE ON public.files TO "{role}"'
        )
        # The consent revocation trigger enforces the existing published
        # profile + delegate revocation in the same SQL transaction. Permit
        # these mutations only on the disposable test role so we can prove
        # that trigger; no privileges are altered in the migration.
        await raw.execute(
            f'GRANT UPDATE ON public.writing_style_profiles, '
            f'public.writing_style_grants TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT ON public.writing_style_grants, '
            f'public.writing_style_sample_evidence TO "{role}"'
        )
        await raw.execute(
            f'GRANT INSERT ON public.writing_style_audit TO "{role}"'
        )
        await raw.execute(
            f'GRANT USAGE ON SEQUENCE public.writing_style_audit_id_seq '
            f'TO "{role}"'
        )

        insert = (
            "INSERT INTO public.writing_style_document_consents "
            "(tenant_id,profile_id,owner_actor_id,artifact_id,author_actor_id,"
            "source_sha256,receipt_id,analysis_allowed,style_use_allowed,"
            "author_attested,expires_at,correlation_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,true,true,true,"
            "clock_timestamp() + interval '1 day','consent-ci')"
        )
        # Neither a foreign actor nor another tenant can manufacture an author
        # receipt for the same canonical document.
        with pytest.raises(asyncpg.PostgresError):
            await scoped(other_actor, tenant, insert,
                         tenant, profile, owner, artifact, owner, digest, receipt)
        with pytest.raises(asyncpg.PostgresError):
            await scoped(owner, foreign_tenant, insert,
                         tenant, profile, owner, artifact, owner, digest, receipt)
        with pytest.raises(asyncpg.PostgresError):
            await scoped(owner, tenant, insert,
                         tenant, profile, owner, artifact, owner,
                         "b" * 64, receipt)

        # A server-side policy callback is required before any issuance.
        engine = create_async_engine(
            dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_size=2, max_overflow=0,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        class TrustedTestClient:
            @asynccontextmanager
            async def get_async_session(self):
                async with sessions() as session:
                    async with session.begin():
                        await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                        yield session

        # The canonical approval repository must consume only the exact
        # approved author action and only within the same caller transaction.
        # A subsequent source INSERT error must roll consumption back.
        approval_id = uuid.uuid4()
        approval_fingerprint = "d" * 64
        approval_payload = {"document_consent_scope": {"action": "issue"}}
        await raw.execute(
            "INSERT INTO public.runtime_approval_requests "
            "(approval_id,tenant_id,user_id,request_fingerprint,intent,"
            "risk_level,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high',CAST($5 AS jsonb),'approved',$3,"
            "'explicit_author_confirmation',clock_timestamp(),"
            "clock_timestamp()+interval '1 hour')",
            approval_id, tenant, owner, approval_fingerprint,
            json.dumps(approval_payload),
        )
        consume_args = dict(
            approval_id=str(approval_id), tenant_id=str(tenant),
            author_actor_id=str(owner), fingerprint=approval_fingerprint,
            action="issue", scope_record=approval_payload["document_consent_scope"],
        )

        # Neither a copied approved status nor an altered durable scope
        # can act as evidence of a deliberate author confirmation.
        for update, args in (
            (
                "UPDATE public.runtime_approval_requests "
                "SET decided_at=NULL WHERE approval_id=$1",
                (approval_id,),
            ),
            (
                "UPDATE public.runtime_approval_requests "
                "SET request_payload='{}'::jsonb WHERE approval_id=$1",
                (approval_id,),
            ),
        ):
            if "decided_at" in update:
                await raw.execute(update, *args)
            else:
                await raw.execute(
                    "UPDATE public.runtime_approval_requests "
                    "SET decided_at=clock_timestamp() WHERE approval_id=$1",
                    approval_id,
                )
                await raw.execute(update, *args)
            async with sessions() as test_session:
                async with test_session.begin():
                    await test_session.execute(
                        text(f'SET LOCAL ROLE "{role}"')
                    )
                    await test_session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": str(tenant)},
                    )
                    assert await SqlApprovalRepository.consume_document_consent_in_session(
                        test_session, **consume_args
                    ) is None
            assert await raw.fetchval(
                "SELECT status FROM public.runtime_approval_requests "
                "WHERE approval_id=$1", approval_id,
            ) == "approved"
        await raw.execute(
            "UPDATE public.runtime_approval_requests "
            "SET request_payload=CAST($1 AS jsonb), "
            "decided_at=clock_timestamp() WHERE approval_id=$2",
            json.dumps(approval_payload), approval_id,
        )

        # Mismatched author is never permitted to consume the receipt.
        async with sessions() as test_session:
            async with test_session.begin():
                await test_session.execute(text(f'SET LOCAL ROLE "{role}"'))
                await test_session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": str(tenant)},
                )
                assert await SqlApprovalRepository.consume_document_consent_in_session(
                    test_session, **{**consume_args, "author_actor_id": str(other_actor)}
                ) is None

        class RollbackApproval(RuntimeError):
            pass

        with pytest.raises(RollbackApproval):
            async with sessions() as test_session:
                async with test_session.begin():
                    await test_session.execute(text(f'SET LOCAL ROLE "{role}"'))
                    await test_session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": str(tenant)},
                    )
                    assert await SqlApprovalRepository.consume_document_consent_in_session(
                        test_session, **consume_args
                    ) is not None
                    raise RollbackApproval()
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", approval_id,
        ) == "approved"

        async with sessions() as test_session:
            async with test_session.begin():
                await test_session.execute(text(f'SET LOCAL ROLE "{role}"'))
                await test_session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": str(tenant)},
                )
                assert await SqlApprovalRepository.consume_document_consent_in_session(
                    test_session, **consume_args
                ) is not None
                assert await SqlApprovalRepository.consume_document_consent_in_session(
                    test_session, **consume_args
                ) is None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", approval_id,
        ) == "consumed"

        scope = dict(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(profile), artifact_id=str(artifact),
        )
        expiry = datetime.now(timezone.utc) + timedelta(days=1)
        absent_policy = PostgresDocumentStyleConsentIssuer(
            client_factory=TrustedTestClient
        )
        assert await absent_policy.issue_first_party(
            **scope, analysis_allowed=True, style_use_allowed=True,
            expires_at=expiry, correlation_id="denied-without-host-policy",
        ) is None

        policy = SimpleNamespace(
            authorize_issuance=AsyncMock(return_value=False),
            authorize_revocation=AsyncMock(return_value=False),
        )
        issuer = PostgresDocumentStyleConsentIssuer(
            client_factory=TrustedTestClient, issuance_policy=policy
        )
        assert await issuer.issue_first_party(
            **scope, analysis_allowed=True, style_use_allowed=True,
            expires_at=expiry, correlation_id="denied-policy",
        ) is None
        policy.authorize_issuance.return_value = True
        bound_session_id = uuid.uuid4().hex
        approval_scope = DocumentConsentApprovalScope(
            tenant_id=str(tenant), author_actor_id=str(owner),
            session_id=bound_session_id, profile_id=str(profile),
            artifact_id=str(artifact), source_sha256=digest,
            action="issue", analysis_allowed=True,
            style_use_allowed=True, expires_at=expiry,
        )
        bound_approval = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.runtime_approval_requests "
            "(approval_id,tenant_id,user_id,request_fingerprint,intent,"
            "risk_level,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high',CAST($5 AS jsonb),'approved',$3,"
            "'explicit_author_confirmation',clock_timestamp(),"
            "clock_timestamp()+interval '1 hour')",
            bound_approval, tenant, owner, approval_scope.fingerprint(),
            json.dumps({"document_consent_scope": approval_scope.to_record()}),
        )
        authenticated = ChatExecutionContext(
            user_id=str(owner), tenant_id=str(tenant),
            session_id=bound_session_id,
            authenticated_user=UserData(
                user_id=str(owner), tenant_id=str(tenant),
                is_active=True, is_verified=True,
            ),
        )
        assert await issuer.issue_with_approved_scope(
            scope=approval_scope, context=authenticated,
            approval_id=str(uuid.uuid4()),
            correlation_id="wrong-approval",
        ) is None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", bound_approval,
        ) == "approved"

        issued = await issuer.issue_with_approved_scope(
            scope=approval_scope, context=authenticated,
            approval_id=str(bound_approval),
            correlation_id="author-affirmative",
        )
        assert issued is not None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", bound_approval,
        ) == "consumed"
        assert await issuer.issue_with_approved_scope(
            scope=approval_scope, context=authenticated,
            approval_id=str(bound_approval),
            correlation_id="replay-denied",
        ) is None
        # A SECOND, independently approved attempt cannot replace the
        # immutable document receipt. Its approval consumption must roll
        # back when the unique document INSERT fails in the same transaction.
        duplicate_approval = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.runtime_approval_requests "
            "(approval_id,tenant_id,user_id,request_fingerprint,intent,"
            "risk_level,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high',CAST($5 AS jsonb),'approved',$3,"
            "'explicit_author_confirmation',clock_timestamp(),"
            "clock_timestamp()+interval '1 hour')",
            duplicate_approval, tenant, owner, approval_scope.fingerprint(),
            json.dumps({"document_consent_scope": approval_scope.to_record()}),
        )
        assert await issuer.issue_with_approved_scope(
            scope=approval_scope, context=authenticated,
            approval_id=str(duplicate_approval),
            correlation_id="duplicate-document-denied",
        ) is None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", duplicate_approval,
        ) == "approved"
        receipt = uuid.UUID(issued)
        assert await raw.fetchval(
            "SELECT receipt_id FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND profile_id=$2 AND artifact_id=$3",
            tenant, profile, artifact,
        ) == receipt
        permission = await issuer.verify_current(**scope)
        assert permission is not None
        assert permission.consent_receipt_id == issued
        assert permission.style_use_allowed is True

        # A repeated affirmative host decision cannot silently replace
        # the immutable receipt or elevate the already-issued permission.
        # The primary-key/immutable-ledger fence owns this replay boundary.
        replayed = await issuer.issue_first_party(
            **scope, analysis_allowed=True, style_use_allowed=False,
            expires_at=expiry, correlation_id="repeated-author-affirmative",
        )
        assert replayed is None
        assert await raw.fetchval(
            "SELECT receipt_id FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND profile_id=$2 AND artifact_id=$3",
            tenant, profile, artifact,
        ) == receipt
        assert (await issuer.verify_current(**scope)).style_use_allowed is True

        # A once-issued receipt is not authorization to use altered or
        # archived bytes. Exercise the real SQL verifier, not a mocked row.
        await raw.execute(
            "UPDATE public.files SET sha256=$1 WHERE file_id=$2",
            "b" * 64, str(artifact),
        )
        assert await issuer.verify_current(**scope) is None
        await raw.execute(
            "UPDATE public.files SET sha256=$1, deleted_at=clock_timestamp() "
            "WHERE file_id=$2",
            digest, str(artifact),
        )
        assert await issuer.verify_current(**scope) is None
        await raw.execute(
            "UPDATE public.files SET deleted_at=NULL WHERE file_id=$1",
            str(artifact),
        )
        assert await issuer.verify_current(**scope) is not None

        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_document_consents "
                "SET style_use_allowed=false WHERE receipt_id=$1",
                receipt,
            )

        # Exercise the actual published-profile and delegated-grant fence,
        # not only a draft with no outstanding authorization to revoke.
        revision = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.writing_style_revisions "
            "(tenant_id,profile_id,revision_id,revision_number,"
            "approved_expression,content_digest,approved_by) "
            "VALUES ($1,$2,$3,1,'{\"tone\":\"direct\"}'::jsonb,$4,$5)",
            tenant, profile, revision, "b" * 64, owner,
        )
        await raw.execute(
            "UPDATE public.writing_style_profiles SET state='published',"
            "publication_revision=1,current_revision_id=$1 "
            "WHERE tenant_id=$2 AND profile_id=$3",
            revision, tenant, profile,
        )
        await raw.execute(
            "INSERT INTO public.writing_style_grants "
            "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,granted_by) "
            "VALUES ($1,$2,$3,$4,'draft_email',$3)",
            tenant, profile, owner, other_actor,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2", tenant, profile,
        ) == "published"

        # A previously valid consent receipt must not authorize a NEW grant
        # when the canonical file has changed. Exercise the owner-scoped
        # repository and its real PostgreSQL query, not a mocked SQL result.
        await raw.execute(
            "UPDATE public.files SET sha256=$1 WHERE file_id=$2",
            "c" * 64, str(artifact),
        )
        with pytest.raises(WritingStyleAccessDenied) as denied:
            await WritingStyleProfileRepository(
                client_factory=TrustedTestClient
            ).grant_use(
                tenant_id=str(tenant), actor_id=str(owner),
                profile_id=str(profile), grantee_actor_id=str(other_actor),
                purpose="draft_email", correlation_id="changed-source-grant",
            )
        assert denied.value.args[0] == "style_source_unavailable"
        await raw.execute(
            "UPDATE public.files SET sha256=$1 WHERE file_id=$2",
            digest, str(artifact),
        )

        # Only one-way revocation is permitted; cannot un-revoke or alter
        # scope/digest/permissions even as the authenticated author.
        assert await issuer.revoke_first_party(
            **scope, correlation_id="deny-revoke",
        ) is False
        policy.authorize_revocation.return_value = True
        assert await issuer.revoke_first_party(
            **scope, correlation_id="author-revoke",
        ) is True
        assert await issuer.verify_current(**scope) is None
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_document_consents "
                "SET revoked_at=NULL WHERE receipt_id=$1",
                receipt,
            )
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL "
            "FROM public.writing_style_document_consents WHERE receipt_id=$1",
            receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2", tenant, profile,
        ) == "revoked"
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL FROM public.writing_style_grants "
            "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
            tenant, profile, other_actor,
        ) is True
    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
