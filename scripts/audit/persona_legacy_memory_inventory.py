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
                "COUNT(*) FILTER (WHERE embedding_id IS NOT NULL) AS embedded "
                "FROM public.persona_memory_entries WHERE tenant_id = :tenant"
            ),
            {"tenant": tenant_id},
        )
        row = rows.one()
    return {
        "total": int(row.total),
        "attributed": int(row.attributed),
        "unattributed": int(row.unattributed),
        "embedded": int(row.embedded),
        "migration_state": "inventory_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inventory(args.tenant_id)), sort_keys=True))


if __name__ == "__main__":
    main()
