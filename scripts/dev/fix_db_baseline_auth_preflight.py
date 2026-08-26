from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Credential Vault review finding: read-only schema verification uses SQL text().
path = ROOT / "src/ai_karen_engine/services/identity_vault/credential_vault_service.py"
text = path.read_text()
old_import = "from sqlalchemy import select, and_, or_, func\n"
new_import = "from sqlalchemy import select, and_, or_, func, text\n"
if old_import in text:
    text = text.replace(old_import, new_import, 1)
elif new_import not in text:
    raise SystemExit("unexpected CredentialVaultService sqlalchemy import")
path.write_text(text)

# Auth runtime performs a real read-only schema preflight and never attempts DDL.
path = ROOT / "src/ai_karen_engine/services/auth/auth_service.py"
text = path.read_text()
start = text.find("    async def _ensure_database_tables(self) -> None:")
end = text.find("    def set_db_session", start)
if start == -1 or end == -1:
    raise SystemExit("AuthService schema-preflight block not found")
replacement = '''    async def _ensure_database_tables(self) -> None:\n        \"\"\"Verify migration-owned auth tables exist; never create schema at runtime.\"\"\"\n        if self._tables_ensured:\n            return\n\n        required = {\n            \"tenants\",\n            \"auth_users\",\n            \"auth_sessions\",\n            \"auth_refresh_token_history\",\n        }\n        try:\n            client = self._get_db_client()\n            async with client.get_async_session() as session:\n                result = await session.execute(\n                    text(\n                        \"SELECT table_name FROM information_schema.tables \"\n                        \"WHERE table_schema = 'public' AND table_name = ANY(:tables)\"\n                    ),\n                    {\"tables\": list(required)},\n                )\n                present = {str(row[0]) for row in result.fetchall()}\n            missing = required - present\n            if missing:\n                raise RuntimeError(\n                    \"Missing migration-owned auth tables: \" + \", \".join(sorted(missing))\n                )\n            self._tables_ensured = True\n            logger.info(\"Migration-owned auth tables verified\")\n        except Exception as e:\n            logger.error(\"Auth schema preflight failed: %s\", e)\n            raise RuntimeError(\"AuthService database preflight failed\") from e\n\n'''
path.write_text(text[:start] + replacement + text[end:])

# The compatibility create API remains a no-op, but no production service may call it.
for service_path in [
    ROOT / "src/ai_karen_engine/services/auth/auth_service.py",
    ROOT / "src/ai_karen_engine/services/identity_vault/credential_vault_service.py",
]:
    if "create_tables_async()" in service_path.read_text(errors="ignore"):
        raise SystemExit(f"runtime table-creation caller survived: {service_path.relative_to(ROOT)}")

print("auth/vault migration-owned schema preflight convergence complete")
