from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [
    "MigrationManager",
    "SCHEMA_MIGRATIONS",
    "create_extension_tables",
    "drop_extension_tables",
    "database.models.identity_vault",
    "create_tables_async()",
    "metadata.create_all",
    "metadata.drop_all",
    "src/ai_karen_engine/database/migrations",
    "docker/database/migrations/postgres",
    "server/chat/migrations",
    "supabase/migrations",
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
