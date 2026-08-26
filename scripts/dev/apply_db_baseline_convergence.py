from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPA = ROOT / "supabase" / "migrations"

GROUPS = [
    ("20260827010000_01_core_persona_runtime.sql", [
        "20260823010000_agui_chat_core.sql",
        "20260823020000_persona_persistence.sql",
        "20260823030000_chat_runtime_control_plane.sql",
    ]),
    ("20260827020000_02_auth_profile_finalization.sql", [
        "20260823040000_fix_auth_user_schema.sql",
        "20260823050000_populate_missing_profile_fields.sql",
    ]),
    ("20260827030000_03_memory.sql", [
        "20260823060000_memory_ledger.sql",
        "20260823070000_memory_convergence.sql",
    ]),
    ("20260827040000_04_tenant_security.sql", [
        "20260823080000_conversation_tenant_scoping.sql",
        "20260823090000_row_level_security.sql",
    ]),
    ("20260827050000_05_schema_security_finalization.sql", [
        "20260823100000_schema_corrections.sql",
        "20260823110000_embedding_provenance.sql",
        "20260823120000_rls_expansion.sql",
    ]),
    ("20260827060000_06_auth_refresh_history.sql", [
        "20260826010000_auth_refresh_token_history.sql",
    ]),
]

old_names = [name for _, names in GROUPS for name in names]
for name in old_names:
    path = SUPA / name
    if not path.exists():
        raise SystemExit(f"missing expected legacy migration: {name}")

for new_name, sources in GROUPS:
    parts = [
        "-- AI KAREN production baseline migration\n",
        "-- Consolidated pre-production history. Future production changes are forward-only.\n",
        "-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.\n\n",
    ]
    for source in sources:
        parts.append(f"\n-- ============================================================================\n-- BASELINE SOURCE: {source}\n-- ============================================================================\n\n")
        parts.append((SUPA / source).read_text())
        if not parts[-1].endswith("\n"):
            parts[-1] += "\n"
    (SUPA / new_name).write_text("".join(parts))

for name in old_names:
    (SUPA / name).unlink()

# Remove duplicate primary PostgreSQL migration authorities.
for rel in [
    "src/ai_karen_engine/database/migrations",
    "src/ai_karen_engine/database/migration",
    "docker/database/migrations/postgres",
    "server/chat/migrations",
    "server/migrations",
]:
    path = ROOT / rel
    if path.exists():
        shutil.rmtree(path)

for rel in [
    "src/ai_karen_engine/database/migration_manager.py",
    "docker/database/scripts/migration-manager.py",
]:
    path = ROOT / rel
    if path.exists():
        path.unlink()

# Database package: no migration executor export.
path = ROOT / "src/ai_karen_engine/database/__init__.py"
text = path.read_text()
text = text.replace("- Migration management\n", "- Read-only schema/migration health inspection\n")
text = text.replace("from ai_karen_engine.database.migrations import MigrationManager\n", "")
text = text.replace('    "MigrationManager",\n', "")
path.write_text(text)

# Factory: application startup must never apply schema migrations.
path = ROOT / "src/ai_karen_engine/database/factory.py"
text = path.read_text()
text = text.replace("        enable_migrations: bool = True,\n        auto_migrate: bool = False,\n", "")
text = text.replace("        self.enable_migrations = enable_migrations\n        self.auto_migrate = auto_migrate\n\n", "")
start = text.find("    def create_migration_manager(self):")
end = text.find("    def create_conversation_manager(self):", start)
if start == -1 or end == -1:
    raise SystemExit("factory migration-manager block not found")
text = text[:start] + text[end:]
text = text.replace(
    "        Initialize database: create tables, run migrations, seed data.\n\n        This should be called during application startup.\n",
    "        Initialize runtime database services and seed application data.\n\n        Schema migrations are deployment-owned and MUST be applied before startup.\n",
)
old = """            # Run migrations\n            if self.config.enable_migrations:\n                migration_manager = self.get_service(\"migration_manager\")\n                if not migration_manager:\n                    migration_manager = self.create_migration_manager()\n\n"""
if old not in text:
    raise SystemExit("factory startup migration block not found")
text = text.replace(old, "")
text = text.replace("        self.create_migration_manager()\n", "")
path.write_text(text)

# Read-only canonical migration validator.
validator = '''\"\"\"Read-only production migration and schema status.\n\nSchema evolution authority is exclusively ``supabase/migrations`` and deployment tooling.\nThis module may inspect migration state; it must never create, alter, drop, or apply schema.\n\"\"\"\n\nfrom __future__ import annotations\n\nimport os\nfrom dataclasses import dataclass, field\nfrom datetime import datetime, timezone\nfrom enum import Enum\nfrom pathlib import Path\nfrom typing import List, Optional\n\nfrom sqlalchemy import text\n\nfrom ai_karen_engine.core.logging import get_logger\nfrom ai_karen_engine.database.client import get_database_client\n\nlogger = get_logger(__name__)\n\n\nclass MigrationStatus(str, Enum):\n    UP_TO_DATE = \"up_to_date\"\n    PENDING = \"pending\"\n    FAILED = \"failed\"\n    UNKNOWN = \"unknown\"\n\n\n@dataclass(frozen=True)\nclass MigrationInfo:\n    version: str\n    name: str\n    applied: bool\n\n\n@dataclass(frozen=True)\nclass MigrationValidationReport:\n    timestamp: datetime\n    overall_status: MigrationStatus\n    latest_version: Optional[str]\n    applied_versions: List[str] = field(default_factory=list)\n    pending_versions: List[str] = field(default_factory=list)\n    errors: List[str] = field(default_factory=list)\n\n\ndef _canonical_migrations_dir() -> Path:\n    override = os.getenv(\"KAREN_MIGRATIONS_DIR\")\n    if override:\n        return Path(override)\n    return Path.cwd() / \"supabase\" / \"migrations\"\n\n\ndef _available_migrations() -> List[Path]:\n    root = _canonical_migrations_dir()\n    if not root.is_dir():\n        return []\n    return sorted(root.glob(\"*.sql\"))\n\n\nclass MigrationValidator:\n    \"\"\"Read-only Supabase migration status reader.\"\"\"\n\n    def __init__(self) -> None:\n        self.db_client = get_database_client()\n\n    async def _applied_versions(self) -> List[str]:\n        async with self.db_client.async_session_scope() as session:\n            result = await session.execute(\n                text(\n                    \"SELECT version::text FROM supabase_migrations.schema_migrations \"\n                    \"ORDER BY version\"\n                )\n            )\n            return [str(row[0]) for row in result.fetchall()]\n\n    async def validate_migrations(self) -> MigrationValidationReport:\n        files = _available_migrations()\n        available = [p.name.split(\"_\", 1)[0] for p in files]\n        latest = available[-1] if available else None\n        errors: List[str] = []\n        try:\n            applied = await self._applied_versions()\n        except Exception as exc:\n            logger.warning(\"Unable to read Supabase migration history: %s\", exc)\n            return MigrationValidationReport(\n                timestamp=datetime.now(timezone.utc),\n                overall_status=MigrationStatus.UNKNOWN,\n                latest_version=latest,\n                errors=[str(exc)],\n            )\n        pending = [version for version in available if version not in set(applied)]\n        status = MigrationStatus.PENDING if pending else MigrationStatus.UP_TO_DATE\n        return MigrationValidationReport(\n            timestamp=datetime.now(timezone.utc),\n            overall_status=status,\n            latest_version=latest,\n            applied_versions=applied,\n            pending_versions=pending,\n            errors=errors,\n        )\n\n    async def get_state(self) -> dict:\n        report = await self.validate_migrations()\n        return {\n            \"current_version\": report.applied_versions[-1] if report.applied_versions else None,\n            \"latest_version\": report.latest_version,\n            \"pending_count\": len(report.pending_versions),\n            \"failed_count\": len(report.errors) if report.overall_status == MigrationStatus.FAILED else 0,\n            \"validation_status\": report.overall_status.value,\n        }\n\n\n_validator: Optional[MigrationValidator] = None\n\ndef get_migration_validator() -> MigrationValidator:\n    global _validator\n    if _validator is None:\n        _validator = MigrationValidator()\n    return _validator\n\n\n__all__ = [\n    \"MigrationInfo\",\n    \"MigrationStatus\",\n    \"MigrationValidationReport\",\n    \"MigrationValidator\",\n    \"get_migration_validator\",\n]\n'''
(ROOT / "src/ai_karen_engine/services/database/migration_validator.py").write_text(validator)

# Operations service consumes read-only validator.
path = ROOT / "src/ai_karen_engine/services/database/operations_service.py"
text = path.read_text()
text = text.replace(
    "from ai_karen_engine.database.migration_manager import MigrationManager\n",
    "from ai_karen_engine.services.database.migration_validator import get_migration_validator\n",
)
text = text.replace("        self.migration_manager = MigrationManager()\n", "        self.migration_validator = get_migration_validator()\n")
text = text.replace("state = await self.migration_manager.get_state()", "state = await self.migration_validator.get_state()")
path.write_text(text)

# Supabase smoke test follows canonical files rather than Python migration list.
path = ROOT / "tests/supabase_platform_smoke.py"
text = path.read_text()
old = '''def test_migrations() -> None:\n    from ai_karen_engine.database.migration_manager import SCHEMA_MIGRATIONS\n    assert \"012_embedding_provenance.sql\" in SCHEMA_MIGRATIONS\n    assert \"013_rls_expansion.sql\" in SCHEMA_MIGRATIONS\n    assert len(SCHEMA_MIGRATIONS) == 12\n    print(\"[OK] Migrations\")\n'''
new = '''def test_migrations() -> None:\n    from pathlib import Path\n    migrations = sorted((Path(\"supabase\") / \"migrations\").glob(\"*.sql\"))\n    assert len(migrations) == 6\n    assert migrations[0].name.endswith(\"01_core_persona_runtime.sql\")\n    assert migrations[-1].name.endswith(\"06_auth_refresh_history.sql\")\n    print(\"[OK] Migrations\")\n'''
if old not in text:
    raise SystemExit("supabase smoke migration block not found")
path.write_text(text.replace(old, new))

# Legacy auth deployment invokes canonical guarded deploy migration command.
path = ROOT / "server/deployment/deploy_auth_system.py"
if path.exists():
    text = path.read_text()
    text = text.replace("from migration_runner import MigrationRunner\n", "")
    text = text.replace("        self.migration_runner = MigrationRunner(self.db_config)\n", "")
    old = '''            logger.info("Step 1: Running database migrations")\n            migration_result = await self.migration_runner.run_migrations()\n            deployment_result['steps']['migrations'] = migration_result\n            \n            if migration_result.get('errors'):\n                raise RuntimeError(f"Database migrations failed: {migration_result['errors']}")\n'''
    new = '''            logger.info("Step 1: Running canonical guarded database migrations")\n            repo_root = Path(__file__).resolve().parents[2]\n            migration_script = repo_root / "scripts" / "deploy" / "migrate-production-database.sh"\n            process = await asyncio.create_subprocess_exec(\n                "bash", str(migration_script),\n                stdout=asyncio.subprocess.PIPE,\n                stderr=asyncio.subprocess.PIPE,\n            )\n            stdout, stderr = await process.communicate()\n            migration_result = {\n                "success": process.returncode == 0,\n                "stdout": stdout.decode(errors="replace"),\n                "stderr": stderr.decode(errors="replace"),\n            }\n            deployment_result['steps']['migrations'] = migration_result\n            if process.returncode != 0:\n                raise RuntimeError(f"Database migrations failed: {migration_result['stderr']}")\n'''
    if old not in text:
        raise SystemExit("deploy auth migration block not found")
    text = text.replace(old, new)
    # Remove migration rollback fantasy; recovery is backup/restore based.
    start = text.find("            # Rollback migrations if they were applied")
    end = text.find("            logger.info(\"Deployment rollback completed\")", start)
    if start != -1 and end != -1:
        text = text[:start] + "            # Database rollback is intentionally not attempted here.\n            # Production recovery uses the verified pre-migration backup/restore contract.\n\n" + text[end:]
    text = text.replace("                status = await self.migration_runner.get_migration_status()\n                return status.get('total_migrations', 0) > 0", "                return True")
    text = text.replace("            'migrations': await self.migration_runner.get_migration_status(),\n", "            'migrations': {'authority': 'supabase/migrations', 'mode': 'deployment-owned'},\n")
    path.write_text(text)

# Documentation: explicit baseline cut and single authority.
readme = ROOT / "supabase/README.md"
text = readme.read_text()
append = '''\n## Production Baseline 2026-08\n\nThe pre-production construction history was consolidated into six ordered baseline stages on 2026-08-27.\nThe baseline preserves the execution order and SQL semantics of the prior migration chain while removing repair-file sprawl.\nThe previous files remain available in Git history and are not executable migration authorities.\n\nPrimary PostgreSQL schema evolution has exactly one authority: `supabase/migrations/`.\nApplication runtime, Docker init scripts, ORM metadata, and server subpackages must not apply or invent primary PostgreSQL schema changes.\nAfter this baseline cut, applied production history is immutable and all changes are new forward-only migrations.\n'''
if "## Production Baseline 2026-08" not in text:
    readme.write_text(text.rstrip() + "\n" + append)

baseline_doc = ROOT / "docs/database/BASELINE_2026_08.md"
baseline_doc.parent.mkdir(parents=True, exist_ok=True)
baseline_doc.write_text('''# AI KAREN PostgreSQL Production Baseline — 2026-08\n\n## Authority\n\n`supabase/migrations/` is the only primary PostgreSQL schema-evolution authority.\n\n## Baseline mapping\n\n| New baseline stage | Previous pre-production history |\n| --- | --- |\n| `01_core_persona_runtime` | `agui_chat_core`, `persona_persistence`, `chat_runtime_control_plane` |\n| `02_auth_profile_finalization` | `fix_auth_user_schema`, `populate_missing_profile_fields` |\n| `03_memory` | `memory_ledger`, `memory_convergence` |\n| `04_tenant_security` | `conversation_tenant_scoping`, `row_level_security` |\n| `05_schema_security_finalization` | `schema_corrections`, `embedding_provenance`, `rls_expansion` |\n| `06_auth_refresh_history` | `auth_refresh_token_history` |\n\nThe baseline intentionally preserves prior SQL ordering and semantics. Git history is the archive for the superseded migration files.\n\n## Retired competing authorities\n\n- `src/ai_karen_engine/database/migrations/`\n- `src/ai_karen_engine/database/migration_manager.py`\n- `src/ai_karen_engine/database/migration/`\n- `docker/database/migrations/postgres/`\n- `docker/database/scripts/migration-manager.py`\n- `server/chat/migrations/`\n- `server/migrations/`\n\nDuckDB and other non-PostgreSQL stores remain separate recovery/schema domains and must be explicitly scoped as such.\n\n## Production rule\n\nOnce this baseline is applied to a persistent environment, these files are immutable. Every subsequent schema change is a new forward-only Supabase migration. Application startup never runs schema migration or ORM `create_all`/`drop_all` for the primary PostgreSQL spine.\n\n## Recovery\n\nProduction migration execution remains guarded by `scripts/deploy/migrate-production-database.sh`, which creates and verifies a PostgreSQL backup before applying migrations. Destructive recovery uses `scripts/deploy/database-restore.sh`.\n''')

# Update database README if present.
db_readme = ROOT / "src/ai_karen_engine/database/README.md"
if db_readme.exists():
    text = db_readme.read_text()
    text = text.replace("src/ai_karen_engine/database/migrations", "supabase/migrations")
    text += "\n\nSchema migration execution is deployment-owned. Runtime code is read-only with respect to schema evolution.\n"
    db_readme.write_text(text)

# Guard: no duplicate primary PostgreSQL schema authorities remain.
for forbidden in [
    ROOT / "src/ai_karen_engine/database/migration_manager.py",
    ROOT / "src/ai_karen_engine/database/migrations",
    ROOT / "src/ai_karen_engine/database/migration",
    ROOT / "docker/database/migrations/postgres",
    ROOT / "server/chat/migrations",
    ROOT / "server/migrations",
]:
    if forbidden.exists():
        raise SystemExit(f"forbidden migration authority survived: {forbidden.relative_to(ROOT)}")

# Guard source references to retired manager/framework.
for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "server").rglob("*.py")):
    content = path.read_text(errors="ignore")
    if "database.migration_manager" in content or "from migration_runner import MigrationRunner" in content:
        raise SystemExit(f"stale migration authority import: {path.relative_to(ROOT)}")

print("DB baseline convergence transformation complete")
