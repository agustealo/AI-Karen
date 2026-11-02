"""CK-28B: canonical deployment fails closed on missing composer draft schema."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts/deploy/verify-composer-draft-schema.sh"
DEPLOY = ROOT / "scripts/deploy/migrate-production-database.sh"


def test_composer_schema_check_is_read_only_and_enforces_owner_boundaries() -> None:
    script = CHECK.read_text(encoding="utf-8")
    assert "to_regclass('public.conversation_composer_drafts')" in script
    assert "composer_draft_schema_missing" in script
    assert "relrowsecurity" in script and "relforcerowsecurity" in script
    assert "conversation_composer_draft_owner" in script
    assert "composer_draft_foreign_keys_missing" in script
    assert "composer_draft_revision_contract_missing" in script
    assert "ON_ERROR_STOP=1" in script
    assert "SELECT * FROM public.conversation_composer_drafts" not in script
    assert "DROP TABLE" not in script


def test_production_migration_requires_draft_schema_proof() -> None:
    script = DEPLOY.read_text(encoding="utf-8")
    assert "database-backup.sh" in script
    assert "supabase db push" in script
    assert "verify-composer-draft-schema.sh" in script
    assert script.index("supabase db push") < script.index("verify-composer-draft-schema.sh")
