"""Planner migration must preserve the canonical Supabase schema authority.

This is a static compatibility preflight, NOT a substitute for applying the
full migration chain on a disposable PostgreSQL database.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "supabase" / "migrations"


def test_planner_foreign_keys_match_upstream_baseline_columns():
    auth = (MIGRATIONS / "20260827010000_01_core_persona_runtime.sql").read_text()
    tenant = (MIGRATIONS / "20260916010000_14_auth_tenant_authority.sql").read_text()
    planner = (MIGRATIONS / "20261020010000_38_personal_planner_commitments.sql").read_text()

    assert "CREATE TABLE auth_users (" in auth
    assert "user_id           UUID PRIMARY KEY" in auth
    assert "CREATE TABLE IF NOT EXISTS public.tenants (" in tenant
    assert "REFERENCES public.tenants(id)" in planner
    assert "REFERENCES public.auth_users(user_id)" in planner
    assert "ALTER TABLE public.automation_tasks" not in planner


def test_planner_migration_is_forward_only_and_has_unique_version():
    paths = sorted(MIGRATIONS.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in paths]
    planner_version = "20261020010000"
    assert versions.count(planner_version) == 1
    assert versions.index(planner_version) > versions.index("20260916010000")
    sql = (MIGRATIONS / "20261020010000_38_personal_planner_commitments.sql").read_text()
    assert sql.count("BEGIN;") == 1
    assert sql.count("COMMIT;") == 1
    assert "DROP TABLE" not in sql
    assert "CREATE TABLE public.personal_planner_commitments" in sql
