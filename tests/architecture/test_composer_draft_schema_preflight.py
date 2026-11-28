"""Composer-draft schema readiness must include runtime SQL privileges.

The existing deployment preflight is read-only. Tests prevent a green schema
check from ignoring missing SELECT/INSERT/UPDATE grants for the API role.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "scripts/deploy/verify-composer-draft-schema.sh"


def test_preflight_requires_schema_rls_policy_and_cas_privileges() -> None:
    script = PREFLIGHT.read_text(encoding="utf-8")
    assert "to_regclass('public.conversation_composer_drafts')" in script
    assert "relrowsecurity" in script and "relforcerowsecurity" in script
    assert "conversation_composer_draft_owner" in script
    assert "composer_draft_revision_contract_missing" in script
    for privilege in ("SELECT", "INSERT", "UPDATE"):
        assert f"has_table_privilege(current_user, drafts, '{privilege}')" in script
    assert "has_schema_privilege(current_user, 'public', 'USAGE')" in script
    assert "composer_draft_runtime_grant_missing" in script


def test_preflight_is_read_only_and_never_echoes_credentials() -> None:
    script = PREFLIGHT.read_text(encoding="utf-8")
    assert "--set=ON_ERROR_STOP=1" in script
    assert "psql" in script and '"${DATABASE_URL}"' in script
    # Detect unintended SQL mutations within the document, ignoring comments.
    sql = script.split("<<'SQL'", 1)[1].split("\nSQL", 1)[0]
    statements = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    ).upper()
    for forbidden in (
        "CREATE TABLE", "DROP TABLE", "ALTER TABLE", "GRANT ",
        "REVOKE ", "INSERT INTO ", "UPDATE ", "DELETE FROM ",
    ):
        assert forbidden not in statements
    assert "echo ${DATABASE_URL}" not in script

def test_preflight_requires_causal_retry_ledger_contract() -> None:
    script = PREFLIGHT.read_text(encoding="utf-8")
    assert "to_regclass('public.runtime_chat_runs')" in script
    assert "runtime_chat_run_scoped_execution" in script
    assert "chat_retry_ledger_security_missing" in script
    assert "retry_prepared_revision" in script and "retry_prepared_at" in script
    assert "ck_runtime_chat_retry_receipt" in script and "convalidated" in script
    assert "chat_retry_receipt_contract_missing" in script
    for privilege in ("SELECT", "UPDATE"):
        assert f"has_table_privilege(current_user, runs, '{privilege}')" in script
    smoke = (ROOT / "scripts/ci/production-first-boot-smoke.sh").read_text(encoding="utf-8")
    assert "bash -s < scripts/deploy/verify-composer-draft-schema.sh" in smoke
    assert smoke.index("bash -s < scripts/deploy/verify-composer-draft-schema.sh") < smoke.index('echo "[smoke] booting production API image"')
