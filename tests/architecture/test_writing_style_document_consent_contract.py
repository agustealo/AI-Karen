"""WS-04A9A: source-independent author-consent schema guardrails.

These tests validate structural safety only. They do not substitute for
disposable-PostgreSQL issuance/revocation tests or authenticated runtime proof.
"""
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase/migrations/20261122010002_62_writing_style_document_author_consent.sql"
)


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_consent_is_separate_from_sample_evidence_and_storage() -> None:
    source = sql()
    assert "create table public.writing_style_document_consents" in source
    assert "references public.writing_style_profiles" in source
    assert "source_sha256 char(64) not null" in source
    assert "unique (tenant_id, receipt_id)" in source
    assert "source text" in source


def test_author_issuance_requires_runtime_scope_and_author_attestation() -> None:
    source = sql()
    assert "author_actor_id = owner_actor_id" in source
    assert "author_attested boolean not null check (author_attested)" in source
    assert "current_setting('app.current_user_id', true)" in source
    assert "current_setting('app.current_tenant_id', true)" in source
    assert "new.analysis_allowed is not true" in source


def test_source_revision_and_archive_must_match_canonical_file() -> None:
    source = sql()
    assert "from public.files f" in source
    assert "f.owner_user_id = new.author_actor_id" in source
    assert "f.tenant_id = new.tenant_id" in source
    assert "f.sha256 = new.source_sha256" in source
    assert "f.deleted_at is null" in source
    assert "f.mime_type = 'text/plain'" in source
    assert "f.bytes between 1 and 65536" in source
    assert "for share" in source


def test_explicit_purposes_and_expiry_cannot_be_relaxed() -> None:
    source = sql()
    assert "analysis_allowed boolean not null check (analysis_allowed)" in source
    assert "style_use_allowed boolean not null default false" in source
    assert "expires_at timestamptz not null" in source
    assert "new.expires_at <= clock_timestamp()" in source
    assert "check (expires_at > issued_at)" in source


def test_receipt_is_immutable_except_one_way_revocation() -> None:
    source = sql()
    assert "old.revoked_at is not null" in source
    assert "new.revoked_at is null" in source
    assert "new.receipt_id" in source
    assert "new.source_sha256" in source
    assert "document style consent is immutable" in source


def test_revocation_fences_published_profile_and_delegates() -> None:
    source = sql()
    assert "after update of revoked_at" in source
    assert "set state = 'revoked'" in source
    assert "update public.writing_style_grants g" in source
    assert "set revoked_at = clock_timestamp()" in source
    assert "'revoke_profile'" in source


def test_private_tenant_rls_is_forced_and_public_access_revoked() -> None:
    source = sql()
    assert "revoke all on public.writing_style_document_consents from public" in source
    assert "enable row level security" in source
    assert "force row level security" in source
    for operation in ("select", "insert", "update"):
        assert f"for {operation}" in source
    assert "for delete" not in source


def test_migration_never_registers_runtime_or_downloads_source() -> None:
    source = sql()
    assert "create function public.writing_style_document_consent_validate()" in source
    assert "create function public.writing_style_document_consent_revoke_fence()" in source
    assert "httpx" not in source
    assert "download(" not in source
    assert "create policy" in source


def test_author_document_discovery_uses_canonical_owner_paging() -> None:
    root = Path(__file__).resolve().parents[2]
    route = (root / "src/ai_karen_engine/api_routes/artifacts.py").read_text(
        encoding="utf-8"
    )
    picker = (
        root
        / "src/ui_launchers/Karen-AI-Theme/src/components/consent/"
        "DocumentAuthorConsentInitiation.tsx"
    ).read_text(encoding="utf-8")
    assert '@router.get("/owner-page"' in route
    assert "store.list_owner_artifacts_page(" in route
    assert '"Owned artifact scope mismatch"' in route
    assert "/api/artifacts/owner-page?limit=100" in picker
    assert "/api/artifacts/'" not in picker
    assert "loadMoreDocuments" in picker
    assert "Document ingestion remains disabled" in picker

def test_effective_file_tenant_uuid_and_forward_consent_repair() -> None:
    """Migration 05, not the original migration 01, owns the effective type."""
    root = Path(__file__).resolve().parents[2]
    base = (
        root / "supabase/migrations/20260827010000_01_core_persona_runtime.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE files (" in base
    base_files = base.split("CREATE TABLE files (", 1)[1].split(");", 1)[0]
    assert "tenant_id     TEXT" in base_files
    normalized = (
        root / "supabase/migrations/20260827050000_05_schema_security_finalization.sql"
    ).read_text(encoding="utf-8")
    assert "ALTER TABLE files" in normalized
    assert "ALTER COLUMN tenant_id TYPE UUID" in normalized
    assert "USING tenant_id::uuid" in normalized

    historical = (
        root / "supabase/migrations/"
        "20261123030000_69_writing_style_document_file_tenant_text.sql"
    ).read_text(encoding="utf-8")
    assert "f.tenant_id = NEW.tenant_id::text" in historical
    repaired = (
        root / "supabase/migrations/"
        "20261123040000_70_writing_style_document_delegated_use_fence.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION public.writing_style_document_consent_validate()" in repaired
    assert "f.tenant_id = NEW.tenant_id" in repaired
    assert "f.tenant_id = NEW.tenant_id::text" not in repaired
    assert "ALTER TABLE public.files" not in repaired

    for expected in (
        "NEW.author_actor_id IS DISTINCT FROM",
        "NEW.author_attested IS NOT TRUE",
        "NEW.expires_at <= clock_timestamp()",
        "f.owner_user_id = NEW.author_actor_id",
        "f.sha256 = NEW.source_sha256",
        "f.deleted_at IS NULL",
        "f.bytes BETWEEN 1 AND 65536",
        "OR OLD.revoked_at IS NOT NULL",
    ):
        assert expected in repaired

    issuer = (
        root / "src/ai_karen_engine/services/"
        "postgres_document_style_consent_issuer.py"
    ).read_text(encoding="utf-8")
    profile_repository = (
        root / "src/ai_karen_engine/services/"
        "writing_style_profile_repository.py"
    ).read_text(encoding="utf-8")
    assert issuer.count("p.tenant_id=f.tenant_id") == 2
    assert issuer.count("f.tenant_id=CAST(:tenant AS uuid)") == 2
    assert "f.tenant_id=c.tenant_id" in issuer
    assert "f.tenant_id=c.tenant_id" in profile_repository
    for code in (issuer, profile_repository, repaired):
        assert "f.tenant_id::text" not in code
        assert "c.tenant_id::text" not in code

    for name in (
        "test_writing_style_document_consent_postgres.py",
        "test_writing_style_identity_postgres.py",
        "test_writing_style_sample_postgres.py",
    ):
        fixture = (root / "tests/integration" / name).read_text(
            encoding="utf-8",
        )
        assert "tenant_id uuid NOT NULL" in fixture
        assert "20261123030000_69_writing_style_document_file_tenant_text.sql" in fixture
        assert "20261123040000_70_writing_style_document_delegated_use_fence.sql" in fixture


def test_document_style_use_fence_reuses_existing_sql_authority() -> None:
    """The forward-only fence must not grant delegates receipt visibility."""
    root = Path(__file__).resolve().parents[2]
    name = "20261123040000_70_writing_style_document_delegated_use_fence.sql"
    migration = (root / "supabase/migrations" / name).read_text(
        encoding="utf-8",
    )
    for clause in (
        "CREATE FUNCTION public.writing_style_document_use_expiry(",
        "SECURITY INVOKER",
        "c.author_attested IS TRUE",
        "c.style_use_allowed IS TRUE",
        "c.receipt_id = s.consent_receipt_id",
        "c.artifact_id = s.source_id",
        "f.tenant_id = c.tenant_id",
        "f.owner_user_id = c.author_actor_id",
        "f.sha256 = c.source_sha256",
        "document_expiry := public.writing_style_document_use_expiry(",
        "PERFORM public.writing_style_document_use_expiry(",
        "CREATE FUNCTION public.writing_style_revoke_consent_on_file_change()",
        "SECURITY DEFINER",
        "SET row_security = off",
        "AFTER UPDATE OF file_id, tenant_id, owner_user_id, name, mime_type, bytes,",
        "sha256, storage_uri, deleted_at OR DELETE",
        "SET revoked_at = clock_timestamp()",
        "OLD.tenant_id",
        "REVOKE ALL ON FUNCTION public.writing_style_revoke_consent_on_file_change()",
    ):
        assert clause in migration

    assert "ALTER TABLE public.files" not in migration
    assert "CREATE TABLE public.writing_style_grants" not in migration
    assert "CREATE TRIGGER writing_style_grant_consent_fence" not in migration
    # No direct grant or profile revocation implementation is duplicated in
    # the new file-trigger function: existing receipt UPDATE owns both.
    file_fence = migration.split(
        "CREATE FUNCTION public.writing_style_revoke_consent_on_file_change()", 1,
    )[1].split("$style_file_mutation_revoke$;", 1)[0]
    assert "UPDATE public.writing_style_document_consents" in file_fence
    assert "UPDATE public.writing_style_profiles" not in file_fence
    assert "UPDATE public.writing_style_grants" not in file_fence
    assert "RETURN NEW;" in file_fence

    for test in (
        "test_writing_style_document_consent_postgres.py",
        "test_writing_style_identity_postgres.py",
        "test_writing_style_sample_postgres.py",
    ):
        path = root / "tests/integration" / test
        content = path.read_text(encoding="utf-8")
        assert name in content
        assert "storage_uri text" in content
