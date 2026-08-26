from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [
    "MigrationManager",
    "SCHEMA_MIGRATIONS",
    "PostgreSQLAuthSchema",
    "IdentityVaultSchema",
    "identity_vault_schema",
    "database.models.identity_vault",
    "class CredentialCreate",
    "class CredentialResponse",
    "class AuditEventType",
    "class LoginStatus",
    "TokenRotationResult",
    "create_schema(",
    "create_tables_async()",
    "create_persona_tables(",
    "identity_providers",
    "credential_secrets",
    "src/ai_karen_engine/database/migrations",
    "docker/database/migrations/postgres",
    "server/chat/migrations",
    "supabase/migrations",
    "create_all(",
    "drop_all(",
    "run_migrations(",
    "schema_migrations",
]
IGNORE = {Path("scripts/dev/audit_db_baseline_dependencies.py")}

for pattern in PATTERNS:
    print(f"\n=== {pattern} ===")
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.relative_to(ROOT) in IGNORE or ".git" in path.parts:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if pattern in text:
            print(path.relative_to(ROOT))

print("\n=== SQL TREES ===")
for base in [
    "supabase/migrations",
    "src/ai_karen_engine/database/migrations",
    "docker/database/migrations/postgres",
    "server/chat/migrations",
]:
    root = ROOT / base
    print(base)
    if root.exists():
        for path in sorted(root.glob("*.sql")):
            print("  ", path.name)
