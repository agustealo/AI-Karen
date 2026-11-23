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

def test_canonical_file_tenant_remains_text_and_consent_uses_safe_casts() -> None:
    """WS-04B4: UUID-shaped consent scope must not change the artifact schema."""
    root = Path(__file__).resolve().parents[2]
    canonical_files = (
        root / "supabase/migrations/20260827010000_01_core_persona_runtime.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE files (" in canonical_files
    files_definition = canonical_files.split("CREATE TABLE files (", 1)[1].split(
        ");", 1,
    )[0]
    assert "tenant_id     TEXT" in files_definition

    migration = (
        root / "supabase/migrations/"
        "20261123030000_69_writing_style_document_file_tenant_text.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION public.writing_style_document_consent_validate()" in migration
    assert "f.tenant_id = NEW.tenant_id::text" in migration
    assert "f.tenant_id::uuid" not in migration
    assert "ALTER TABLE public.files" not in migration
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
        assert expected in migration

    issuer = (
        root / "src/ai_karen_engine/services/"
        "postgres_document_style_consent_issuer.py"
    ).read_text(encoding="utf-8")
    profile_repository = (
        root / "src/ai_karen_engine/services/"
        "writing_style_profile_repository.py"
    ).read_text(encoding="utf-8")

    assert issuer.count("p.tenant_id::text=f.tenant_id") == 2
    assert issuer.count("f.tenant_id=CAST(:tenant AS uuid)::text") == 2
    assert "f.tenant_id=c.tenant_id::text" in issuer
    assert "f.tenant_id=c.tenant_id::text" in profile_repository

    for source in (issuer, profile_repository):
        assert "f.tenant_id::uuid" not in source

    for name in (
        "test_writing_style_document_consent_postgres.py",
        "test_writing_style_identity_postgres.py",
        "test_writing_style_sample_postgres.py",
    ):
        fixture = (root / "tests/integration" / name).read_text(
            encoding="utf-8",
        )
        assert "tenant_id text NOT NULL" in fixture
        assert "20261123030000_69_writing_style_document_file_tenant_text.sql" in fixture
