"""Read-only inventory for retiring persona_memory_entries safely.

Run only against an explicitly selected database using the authenticated
operator's tenant scope. Emits counts, never personal contents or identifiers.
No migration, mutation, permission elevation, or cross-tenant enumeration.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


async def inventory(tenant_id: str) -> dict[str, object]:
    if not tenant_id.strip() or tenant_id.strip() == "default":
        raise ValueError("Explicit non-default tenant scope required")
    async with async_transaction_scope(tenant_id=tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT "
                "COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE persona_id IS NOT NULL) AS attributed, "
                "COUNT(*) FILTER (WHERE persona_id IS NULL) AS unattributed, "
                "COUNT(*) FILTER (WHERE embedding_id IS NOT NULL) AS embedded, "
                "COUNT(*) FILTER (WHERE content IS NULL OR btrim(content) = '') AS empty_content, "
                "COUNT(*) FILTER (WHERE user_id !~* :uuid_pattern) AS invalid_user_identity, "
                "COUNT(*) FILTER (WHERE tenant_id !~* :uuid_pattern) AS invalid_tenant_identity "
                "FROM public.persona_memory_entries WHERE tenant_id = :tenant"
            ),
            {"tenant": tenant_id, "uuid_pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"},
        )
        row = rows.one()
    return {
        "total": int(row.total),
        "attributed": int(row.attributed),
        "unattributed": int(row.unattributed),
        "embedded": int(row.embedded),
        "empty_content": int(row.empty_content),
        "invalid_user_identity": int(row.invalid_user_identity),
        "invalid_tenant_identity": int(row.invalid_tenant_identity),
        "migration_eligible": 0,
        "eligibility_status": "unverified_consent_and_identity",
        "migration_state": "inventory_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inventory(args.tenant_id)), sort_keys=True))


if __name__ == "__main__":
    main()
