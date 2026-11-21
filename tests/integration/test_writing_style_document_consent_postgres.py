"""WS-04A9B: real disposable PostgreSQL author-consent ledger acceptance.

Runs after the canonical WS-02 tests in the existing /karen_writing_style_test
database. Never accesses production databases, Supabase Storage, or source bytes.
This does NOT verify authorship outside authenticated first-party attestation.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio


async def test_first_party_author_consent_postgres() -> None:
    dsn = os.getenv("WRITING_STYLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated writing-style disposable PostgreSQL not configured")
    if urlparse(dsn).path != "/karen_writing_style_test":
        pytest.fail("Refuse to run against a non-disposable database")

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
            DROP TABLE IF EXISTS public.writing_style_document_consents CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_sample_evidence CASCADE;
            DROP TABLE IF EXISTS public.writing_style_audit CASCADE;
            DROP TABLE IF EXISTS public.writing_style_grants CASCADE;
            DROP TABLE IF EXISTS public.writing_style_revisions CASCADE;
            DROP TABLE IF EXISTS public.writing_style_profiles CASCADE;
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
                deleted_at timestamptz
            );
        """)
        for filename in (
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
            f'GRANT SELECT ON public.files, public.writing_style_profiles '
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

        await scoped(owner, tenant, insert,
                     tenant, profile, owner, artifact, owner, digest, receipt)
        assert await raw.fetchval(
            "SELECT receipt_id FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND profile_id=$2 AND artifact_id=$3",
            tenant, profile, artifact,
        ) == receipt

        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_document_consents "
                "SET style_use_allowed=false WHERE receipt_id=$1",
                receipt,
            )

        # Only one-way revocation is permitted; cannot un-revoke or alter
        # scope/digest/permissions even as the authenticated author.
        await scoped(
            owner, tenant,
            "UPDATE public.writing_style_document_consents "
            "SET revoked_at=clock_timestamp() WHERE receipt_id=$1",
            receipt,
        )
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
    finally:
        await raw.close()
