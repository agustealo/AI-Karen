"""WS-04A9B: real disposable PostgreSQL author-consent ledger acceptance.

Runs after the canonical WS-02 tests in the existing /karen_writing_style_test
database. Never accesses production databases, Supabase Storage, or source bytes.
This does NOT verify authorship outside authenticated first-party attestation.
"""
from __future__ import annotations

import asyncio
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

from fastapi import Request

from ai_karen_engine.auth import auth_middleware, session as auth_session
from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureRevision,
)
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
)
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    RuntimePolicyEnforcer,
)
from ai_karen_engine.services.postgres_document_style_consent_issuer import (
    PostgresDocumentStyleConsentIssuer,
    RuntimeDocumentConsentPolicy,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleAccessDenied,
    WritingStyleProfileRepository,
)

pytestmark = pytest.mark.asyncio


async def test_first_party_author_consent_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            DROP FUNCTION IF EXISTS public.writing_style_document_use_expiry(uuid,uuid,uuid) CASCADE;
            DROP FUNCTION IF EXISTS public.writing_style_revoke_consent_on_file_change() CASCADE;
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
                storage_uri text,
                deleted_at timestamptz
            );
        """)
        for filename in (
            "20261006030000_26_runtime_human_approval_authority.sql",
            "20261120235900_60_writing_style_identity.sql",
            "20261122010001_61_writing_style_sample_evidence.sql",
            "20261122010002_62_writing_style_document_author_consent.sql",
            "20261123030000_69_writing_style_document_file_tenant_text.sql",
            "20261123040000_70_writing_style_document_delegated_use_fence.sql",
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
            f'GRANT INSERT ON public.writing_style_grants, '
            f'public.writing_style_sample_evidence TO "{role}"'
        )
        await raw.execute(
            f'GRANT SELECT ON public.writing_style_grants, '
            f'public.writing_style_sample_evidence, '
            f'public.writing_style_revisions TO "{role}"'
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

        # Governed profile inventory must not enumerate foreign actors or
        # tenants, and must stop exposing a formerly eligible draft.
        draft_repo = WritingStyleProfileRepository(client_factory=TrustedTestClient)
        owned = await draft_repo.list_owned_drafts(
            tenant_id=str(tenant), actor_id=str(owner),
        )
        assert any(item["profile_id"] == str(profile) for item in owned)
        assert await draft_repo.list_owned_drafts(
            tenant_id=str(tenant), actor_id=str(other_actor),
        ) == []
        assert await draft_repo.list_owned_drafts(
            tenant_id=str(foreign_tenant), actor_id=str(owner),
        ) == []
        with pytest.raises(ValueError, match="invalid_style_profile_page_limit"):
            await draft_repo.list_owned_drafts(
                tenant_id=str(tenant), actor_id=str(owner), limit=101,
            )

        # The canonical approval repository must consume only the exact
        # approved author action and only within the same caller transaction.
        # A subsequent source INSERT error must roll consumption back.
        approval_id = uuid.uuid4()
        approval_fingerprint = "d" * 64
        approval_payload = {"document_consent_scope": {"action": "issue"}}
        await raw.execute(
            "INSERT INTO public.runtime_approval_requests "
            "(approval_id,tenant_id,user_id,request_fingerprint,intent,"
            "risk_level,policy_decision_id,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high','policy-document-consent-preflight-disposable-author',CAST($5 AS jsonb),'approved',$3,"
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

        # Neither missing provenance nor an unrelated policy decision
        # can authorize a document-consent CAS, even when approved is set.
        for policy_id in (None, "policy-other-approved-action"):
            await raw.execute(
                "UPDATE public.runtime_approval_requests "
                "SET policy_decision_id=$1 WHERE approval_id=$2",
                policy_id, approval_id,
            )
            async with sessions() as test_session:
                async with test_session.begin():
                    await test_session.execute(text(f'SET LOCAL ROLE "{role}"'))
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
            "SET policy_decision_id='policy-document-consent-preflight-disposable-author' "
            "WHERE approval_id=$1", approval_id,
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

        # The persisted approval TTL is an independent SQL admission check.
        # A still-valid bearer and matching author/source cannot extend it.
        await raw.execute(
            "UPDATE public.runtime_approval_requests "
            "SET expires_at=clock_timestamp()-interval '1 second' "
            "WHERE approval_id=$1", approval_id,
        )
        async with sessions() as test_session:
            async with test_session.begin():
                await test_session.execute(text(f'SET LOCAL ROLE "{role}"'))
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
            "SET expires_at=clock_timestamp()+interval '1 hour' "
            "WHERE approval_id=$1", approval_id,
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
        # Recovery reads exactly the original durable scope after consumption;
        # a generic consumed-approval purge must not erase this binding.
        persisted_scope = await raw.fetchval(
            "SELECT request_payload -> 'document_consent_scope' "
            "FROM public.runtime_approval_requests WHERE approval_id=$1",
            approval_id,
        )
        assert json.loads(persisted_scope) == approval_payload["document_consent_scope"]

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
        # Even an affirmative host policy alone must never bypass the
        # durable author-confirmed approval and one-shot atomic CAS.
        assert await issuer.issue_first_party(
            **scope, analysis_allowed=True, style_use_allowed=True,
            expires_at=expiry, correlation_id="denied-legacy-policy-boolean",
        ) is None
        # Use the actual canonical active-session validator, not a
        # synthetic ChatExecutionContext supplied to the issuer.
        bearer = "test-bearer-for-disposable-postgresql"
        claims = {
            "sub": str(owner), "tenant_id": str(tenant),
            "token_id": "verified-document-author-session",
            "roles": ["user"], "permissions": [],
        }
        verifier = SimpleNamespace(
            validate_token=AsyncMock(return_value={
                "status": auth_middleware.TokenStatus.VALID,
                "payload": claims,
            }),
            _get_user_from_payload=lambda payload: {
                "user_id": payload["sub"],
                "tenant_id": payload["tenant_id"],
                "roles": payload["roles"],
                "permissions": payload["permissions"],
            },
        )
        monkeypatch.setattr(
            auth_session.auth_config, "should_bypass_auth", lambda: False,
        )
        monkeypatch.setattr(
            auth_session, "_get_auth_middleware", lambda: verifier,
        )
        bearer_request = Request({
            "type": "http", "method": "POST",
            "path": "/internal/document-style-consent",
            "root_path": "", "scheme": "https",
            "headers": [
                (b"authorization", ("Bearer " + bearer).encode("ascii")),
            ],
            "query_string": b"", "server": ("localhost", 443),
        })
        verified_context = await auth_session.get_document_style_consent_context(
            bearer_request,
        )
        approval_scope = DocumentConsentApprovalScope(
            tenant_id=str(tenant), author_actor_id=str(owner),
            session_id=verified_context.session_id, profile_id=str(profile),
            artifact_id=str(artifact), source_sha256=digest,
            action="issue", analysis_allowed=True,
            style_use_allowed=True, expires_at=expiry,
        )
        # Production-shaped policy: use the canonical RuntimePolicyEnforcer
        # instead of a boolean AsyncMock for the actual approval/receipt flow.
        runtime_issuer = PostgresDocumentStyleConsentIssuer(
            client_factory=TrustedTestClient,
            issuance_policy=RuntimeDocumentConsentPolicy(
                RuntimePolicyEnforcer(),
            ),
        )
        bound_approval = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.runtime_approval_requests "
            "(approval_id,tenant_id,user_id,request_fingerprint,intent,"
            "risk_level,policy_decision_id,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high','policy-document-consent-preflight-disposable-author',CAST($5 AS jsonb),'approved',$3,"
            "'explicit_author_confirmation',clock_timestamp(),"
            "clock_timestamp()+interval '1 hour')",
            bound_approval, tenant, owner, approval_scope.fingerprint(),
            json.dumps({"document_consent_scope": approval_scope.to_record()}),
        )
        assert await runtime_issuer.issue_with_approved_scope(
            scope=approval_scope, request=bearer_request,
            approval_id=str(uuid.uuid4()),
            correlation_id="wrong-approval",
        ) is None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", bound_approval,
        ) == "approved"

        # A just-revoked bearer session cannot consume an otherwise
        # valid and already human-confirmed approval.
        verifier.validate_token.return_value = {
            "status": auth_middleware.TokenStatus.REVOKED,
            "payload": claims,
        }
        assert await runtime_issuer.issue_with_approved_scope(
            scope=approval_scope, request=bearer_request,
            approval_id=str(bound_approval),
            correlation_id="revoked-session-denied",
        ) is None
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", bound_approval,
        ) == "approved"
        verifier.validate_token.return_value = {
            "status": auth_middleware.TokenStatus.VALID,
            "payload": claims,
        }
        # Two real database transactions race for the SAME approved action.
        # The repository CAS must admit exactly one and the receipt insert
        # must be committed in that winning transaction only.
        attempts = await asyncio.gather(
            *(
                runtime_issuer.issue_with_approved_scope(
                    scope=approval_scope, request=bearer_request,
                    approval_id=str(bound_approval),
                    correlation_id=f"concurrent-author-{index}",
                )
                for index in range(2)
            )
        )
        successful = [value for value in attempts if value is not None]
        assert len(successful) == 1
        assert attempts.count(None) == 1
        issued = successful[0]
        assert await raw.fetchval(
            "SELECT count(*) FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND profile_id=$2 AND artifact_id=$3",
            tenant, profile, artifact,
        ) == 1
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests "
            "WHERE approval_id=$1", bound_approval,
        ) == "consumed"
        consumed_scope = await raw.fetchval(
            "SELECT request_payload -> 'document_consent_scope' "
            "FROM public.runtime_approval_requests WHERE approval_id=$1",
            bound_approval,
        )
        assert json.loads(consumed_scope) == approval_scope.to_record()
        assert await runtime_issuer.issue_with_approved_scope(
            scope=approval_scope, request=bearer_request,
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
            "risk_level,policy_decision_id,request_payload,status,decided_by,decision_reason,decided_at,expires_at) "
            "VALUES ($1,$2,$3,$4,'writing_style.document_consent.issue',"
            "'high','policy-document-consent-preflight-disposable-author',CAST($5 AS jsonb),'approved',$3,"
            "'explicit_author_confirmation',clock_timestamp(),"
            "clock_timestamp()+interval '1 hour')",
            duplicate_approval, tenant, owner, approval_scope.fingerprint(),
            json.dumps({"document_consent_scope": approval_scope.to_record()}),
        )
        assert await runtime_issuer.issue_with_approved_scope(
            scope=approval_scope, request=bearer_request,
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
        summary = await runtime_issuer.read_current_source_summary(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(profile), artifact_id=str(artifact),
            source_sha256=digest,
        )
        assert summary == {
            "name": "author.txt", "bytes": 10, "mime_type": "text/plain",
        }
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

        # A mismatched expected digest never reveals private metadata.
        # File drift now revokes irreversibly; test it on separate receipts.
        assert await runtime_issuer.read_current_source_summary(
            tenant_id=str(tenant), actor_id=str(owner),
            profile_id=str(profile), artifact_id=str(artifact),
            source_sha256="b" * 64,
        ) is None
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

        # The independent direct-SQL and source-drift matrix below tests
        # changed canonical file metadata after a delegated grant exists.
        # Only one-way revocation is permitted; cannot un-revoke or alter
        # scope/digest/permissions even as the authenticated author.
        assert await issuer.revoke_first_party(
            **scope, correlation_id="deny-revoke", request=bearer_request,
        ) is False
        policy.authorize_revocation.return_value = True
        verifier.validate_token.return_value = {
            "status": auth_middleware.TokenStatus.REVOKED,
            "payload": claims,
        }
        assert await issuer.revoke_first_party(
            **scope, correlation_id="revoked-bearer-denied",
            request=bearer_request,
        ) is False
        assert await raw.fetchval(
            "SELECT revoked_at IS NULL "
            "FROM public.writing_style_document_consents "
            "WHERE receipt_id=$1", receipt,
        ) is True
        verifier.validate_token.return_value = {
            "status": auth_middleware.TokenStatus.VALID,
            "payload": claims,
        }
        # Revoke current consent voluntarily before mutating its file.
        # The wrong digest remains denied without changing the receipt.
        assert await issuer.revoke_first_party(
            **scope, correlation_id="wrong-source-revoke",
            request=bearer_request, expected_source_sha256="b" * 64,
        ) is False
        assert await issuer.revoke_first_party(
            **scope, correlation_id="author-revoke", request=bearer_request,
            expected_source_sha256=digest,
        ) is True
        assert await issuer.verify_current(**scope) is None
        # Editing the canonical file after revocation cannot restore consent.
        await raw.execute(
            "UPDATE public.files SET deleted_at=clock_timestamp() "
            "WHERE file_id=$1", str(artifact),
        )
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
        # Prove the actual delegated-use runtime owner denies the same
        # previously granted actor and published revision after revocation.
        delegated_request = KariSignatureRequest(
            tenant_id=str(tenant),
            actor_id=str(other_actor),
            profile_id=str(profile),
            purpose="draft_email",
            correlation_id="post-revocation-use-denied",
        )
        published_revision = KariSignatureRevision(
            tenant_id=str(tenant),
            profile_id=str(profile),
            revision_id=str(revision),
            revision_number=1,
            state="published",
            approved_expression={"tone": "direct"},
            content_digest="b" * 64,
        )
        delegated_owner = WritingStyleProfileRepository(
            client_factory=TrustedTestClient,
        )
        assert await delegated_owner.read_current_published(
            request=delegated_request,
        ) is None
        assert await delegated_owner.authorize_use(
            request=delegated_request, revision=published_revision,
        ) is False

        # P2 regression: an author can revoke consent while the profile is
        # still draft, including after evidence has been registered. The
        # database must prevent both later publication and direct SQL grants.
        draft_profile = uuid.uuid4()
        draft_artifact = uuid.uuid4()
        draft_receipt = uuid.uuid4()
        draft_sample = uuid.uuid4()
        draft_revision = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.writing_style_profiles "
            "(tenant_id,profile_id,owner_actor_id,kind,label) "
            "VALUES ($1,$2,$3,'personal','Pending author document')",
            tenant, draft_profile, owner,
        )
        await raw.execute(
            "INSERT INTO public.files "
            "(file_id,tenant_id,owner_user_id,name,mime_type,bytes,sha256) "
            "VALUES ($1,$2,$3,'pending.txt','text/plain',10,$4)",
            str(draft_artifact), tenant, owner, digest,
        )
        await scoped(
            owner, tenant,
            "INSERT INTO public.writing_style_document_consents "
            "(tenant_id,profile_id,owner_actor_id,artifact_id,author_actor_id,"
            "source_sha256,receipt_id,analysis_allowed,style_use_allowed,"
            "author_attested,expires_at,correlation_id) "
            "VALUES ($1,$2,$3,$4,$3,$5,$6,true,true,true,"
            "clock_timestamp()+interval '1 day','draft-author-attested')",
            tenant, draft_profile, owner, draft_artifact, digest, draft_receipt,
        )
        await raw.execute(
            "INSERT INTO public.writing_style_sample_evidence "
            "(tenant_id,profile_id,owner_actor_id,sample_id,source_type,"
            "source_id,source_author_id,consent_receipt_id,analysis_allowed,"
            "style_use_allowed,consent_expires_at) "
            "VALUES ($1,$2,$3,$4,'document',$5,$3,$6,true,true,"
            "clock_timestamp()+interval '1 day')",
            tenant, draft_profile, owner, draft_sample,
            draft_artifact, draft_receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2",
            tenant, draft_profile,
        ) == "draft"
        await scoped(
            owner, tenant,
            "UPDATE public.writing_style_document_consents "
            "SET revoked_at=clock_timestamp() "
            "WHERE tenant_id=$1 AND profile_id=$2 AND receipt_id=$3",
            tenant, draft_profile, draft_receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2",
            tenant, draft_profile,
        ) == "revoked"
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL "
            "FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND receipt_id=$2",
            tenant, draft_receipt,
        ) is True
        # The sample metadata may still contain old style_use_allowed=true:
        # its authority was revoked by the profile lifecycle, not by a
        # mutable or browser-owned evidence Boolean.
        assert await raw.fetchval(
            "SELECT style_use_allowed FROM public.writing_style_sample_evidence "
            "WHERE tenant_id=$1 AND profile_id=$2 AND sample_id=$3",
            tenant, draft_profile, draft_sample,
        ) is True
        await raw.execute(
            "INSERT INTO public.writing_style_revisions "
            "(tenant_id,profile_id,revision_id,revision_number,"
            "approved_expression,content_digest,approved_by) "
            "VALUES ($1,$2,$3,1,'{}'::jsonb,$4,$5)",
            tenant, draft_profile, draft_revision, "d" * 64, owner,
        )
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_profiles "
                "SET state='published',publication_revision=1,current_revision_id=$1 "
                "WHERE tenant_id=$2 AND profile_id=$3",
                draft_revision, tenant, draft_profile,
            )
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "INSERT INTO public.writing_style_grants "
                "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,granted_by) "
                "VALUES ($1,$2,$3,$4,'draft_email',$3)",
                tenant, draft_profile, owner, other_actor,
            )


        # WS-04B5: use the real canonical SQL trigger as the authority. Direct
        # owner SQL cannot issue an unbounded delegated grant over an expiring
        # author-attested document, and the delegate sees only current state.
        async def published_document_case():
            case_profile, case_file, case_receipt, case_revision = (
                uuid.uuid4() for _ in range(4)
            )
            await raw.execute(
                "INSERT INTO public.writing_style_profiles "
                "(tenant_id,profile_id,owner_actor_id,kind,label) "
                "VALUES ($1,$2,$3,'personal','Document grant SQL fence')",
                tenant, case_profile, owner,
            )
            await raw.execute(
                "INSERT INTO public.files "
                "(file_id,tenant_id,owner_user_id,name,mime_type,bytes,sha256) "
                "VALUES ($1,$2,$3,'document.txt','text/plain',10,$4)",
                str(case_file), tenant, owner, digest,
            )
            await scoped(
                owner, tenant, insert,
                tenant, case_profile, owner, case_file, owner, digest,
                case_receipt,
            )
            await raw.execute(
                "INSERT INTO public.writing_style_revisions "
                "(tenant_id,profile_id,revision_id,revision_number,"
                "approved_expression,content_digest,approved_by) "
                "VALUES ($1,$2,$3,1,'{\"tone\":\"direct\"}'::jsonb,$4,$5)",
                tenant, case_profile, case_revision, "b" * 64, owner,
            )
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_profiles "
                "SET state='published',publication_revision=1,"
                "current_revision_id=$1 WHERE tenant_id=$2 AND profile_id=$3",
                case_revision, tenant, case_profile,
            )
            return case_profile, case_file, case_receipt, case_revision

        direct_profile, direct_file, direct_receipt, direct_revision = (
            await published_document_case()
        )
        await scoped(
            owner, tenant,
            "INSERT INTO public.writing_style_grants "
            "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,granted_by) "
            "VALUES ($1,$2,$3,$4,'draft_email',$3)",
            tenant, direct_profile, owner, other_actor,
        )
        original_expiry = await raw.fetchval(
            "SELECT expires_at FROM public.writing_style_document_consents "
            "WHERE receipt_id=$1", direct_receipt,
        )
        assert await raw.fetchval(
            "SELECT expires_at FROM public.writing_style_grants "
            "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3 "
            "AND purpose='draft_email'",
            tenant, direct_profile, other_actor,
        ) == original_expiry

        # Direct owner SQL cannot stretch a grant past its source consent.
        for extension in (
            "UPDATE public.writing_style_grants SET expires_at=NULL "
            "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
            "UPDATE public.writing_style_grants "
            "SET expires_at=clock_timestamp()+interval '20 days' "
            "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
        ):
            await scoped(owner, tenant, extension, tenant, direct_profile, other_actor)
            assert await raw.fetchval(
                "SELECT expires_at FROM public.writing_style_grants "
                "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
                tenant, direct_profile, other_actor,
            ) == original_expiry

        delegated_req = KariSignatureRequest(
            tenant_id=str(tenant), actor_id=str(other_actor),
            profile_id=str(direct_profile), purpose="draft_email",
            correlation_id="ws04b5-direct-sql-valid",
        )
        direct_repo = WritingStyleProfileRepository(
            client_factory=TrustedTestClient,
        )
        active_revision = await direct_repo.read_current_published(
            request=delegated_req,
        )
        assert active_revision is not None
        assert await direct_repo.authorize_use(
            request=delegated_req, revision=active_revision,
        ) is True

        # A no-op metadata write must not destroy a valid author receipt.
        await raw.execute(
            "UPDATE public.files SET sha256=sha256 WHERE file_id=$1",
            str(direct_file),
        )
        assert await raw.fetchval(
            "SELECT revoked_at IS NULL FROM public.writing_style_document_consents "
            "WHERE receipt_id=$1", direct_receipt,
        ) is True

        # Source drift, archival, deletion and owner/tenant moves are all
        # irreversible revocation events. They must stop previously authorized
        # delegate resolution without delegate SELECT on private receipts.
        changes = (
            ("digest", "UPDATE public.files SET sha256=$2 WHERE file_id=$1", "c" * 64),
            ("archive", "UPDATE public.files SET deleted_at=clock_timestamp() WHERE file_id=$1", None),
            ("mime", "UPDATE public.files SET mime_type='application/pdf' WHERE file_id=$1", None),
            ("size", "UPDATE public.files SET bytes=11 WHERE file_id=$1", None),
            ("name", "UPDATE public.files SET name='changed.txt' WHERE file_id=$1", None),
            ("storage", "UPDATE public.files SET storage_uri='supabase://new-source' WHERE file_id=$1", None),
            ("owner", "UPDATE public.files SET owner_user_id=$2 WHERE file_id=$1", other_actor),
            ("tenant", "UPDATE public.files SET tenant_id=$2 WHERE file_id=$1", foreign_tenant),
            ("delete", "DELETE FROM public.files WHERE file_id=$1", None),
        )
        for label, update_statement, replacement in changes:
            case_profile, case_file, case_receipt, case_revision = (
                await published_document_case()
            )
            await scoped(
                owner, tenant,
                "INSERT INTO public.writing_style_grants "
                "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,granted_by) "
                "VALUES ($1,$2,$3,$4,'draft_email',$3)",
                tenant, case_profile, owner, other_actor,
            )
            prior = KariSignatureRequest(
                tenant_id=str(tenant), actor_id=str(other_actor),
                profile_id=str(case_profile), purpose="draft_email",
                correlation_id="ws04b5-" + label,
            )
            before = await direct_repo.read_current_published(request=prior)
            assert before is not None, label
            if label == "digest":
                # A non-owner file actor cannot bypass the SECURITY DEFINER
                # consent fence (fixture privileges are disposable only).
                await scoped(other_actor, tenant, update_statement,
                             str(case_file), replacement)
            elif replacement is None:
                await raw.execute(update_statement, str(case_file))
            else:
                await raw.execute(update_statement, str(case_file), replacement)
            assert await raw.fetchval(
                "SELECT revoked_at IS NOT NULL "
                "FROM public.writing_style_document_consents "
                "WHERE receipt_id=$1", case_receipt,
            ) is True, label
            assert await raw.fetchval(
                "SELECT state FROM public.writing_style_profiles "
                "WHERE tenant_id=$1 AND profile_id=$2",
                tenant, case_profile,
            ) == "revoked", label
            assert await raw.fetchval(
                "SELECT revoked_at IS NOT NULL "
                "FROM public.writing_style_grants "
                "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
                tenant, case_profile, other_actor,
            ) is True, label
            assert await direct_repo.read_current_published(request=prior) is None, label
            assert not await direct_repo.authorize_use(
                request=prior, revision=before,
            ), label
            if label == "digest":
                # Restoring metadata never reopens immutable receipt or grants.
                await raw.execute(
                    "UPDATE public.files SET sha256=$2 WHERE file_id=$1",
                    str(case_file), digest,
                )
                assert await direct_repo.read_current_published(request=prior) is None
                with pytest.raises(asyncpg.PostgresError):
                    await scoped(
                        owner, tenant,
                        "UPDATE public.writing_style_grants "
                        "SET revoked_at=NULL, expires_at=NULL "
                        "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
                        tenant, case_profile, other_actor,
                    )

        # A document sample without an independently issued matching receipt
        # cannot be laundered into publication or a delegated grant via SQL.
        unattested_profile, unattested_sample, unattested_source = (
            uuid.uuid4() for _ in range(3)
        )
        unattested_revision = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.writing_style_profiles "
            "(tenant_id,profile_id,owner_actor_id,kind,label) "
            "VALUES ($1,$2,$3,'personal','Unattested sample')",
            tenant, unattested_profile, owner,
        )
        await scoped(
            owner, tenant,
            "INSERT INTO public.writing_style_sample_evidence "
            "(tenant_id,profile_id,owner_actor_id,sample_id,source_type,"
            "source_id,source_author_id,consent_receipt_id,"
            "analysis_allowed,style_use_allowed,consent_expires_at) "
            "VALUES ($1,$2,$3,$4,'document',$5,$3,$6,true,true,"
            "clock_timestamp()+interval '1 day')",
            tenant, unattested_profile, owner, unattested_sample,
            unattested_source, uuid.uuid4(),
        )
        await raw.execute(
            "INSERT INTO public.writing_style_revisions "
            "(tenant_id,profile_id,revision_id,revision_number,"
            "approved_expression,content_digest,approved_by) "
            "VALUES ($1,$2,$3,1,'{}'::jsonb,$4,$5)",
            tenant, unattested_profile, unattested_revision, "d" * 64, owner,
        )
        with pytest.raises(asyncpg.PostgresError, match="source use consent unavailable"):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_profiles "
                "SET state='published',publication_revision=1,"
                "current_revision_id=$1 WHERE tenant_id=$2 AND profile_id=$3",
                unattested_revision, tenant, unattested_profile,
            )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2",
            tenant, unattested_profile,
        ) == "draft"

    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
