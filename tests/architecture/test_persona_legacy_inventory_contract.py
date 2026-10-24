"""Legacy inventory is read-only and never asserts migration eligibility."""
from __future__ import annotations

import ast
from pathlib import Path


INVENTORY = Path("scripts/audit/persona_legacy_memory_inventory.py")


def test_inventory_compiles():
    ast.parse(INVENTORY.read_text(encoding="utf-8"), filename=str(INVENTORY))


def test_inventory_requires_scope_and_only_counts_records():
    source = INVENTORY.read_text(encoding="utf-8")
    assert "Explicit non-default tenant scope required" in source
    assert "WHERE tenant_id = :tenant" in source
    assert "invalid_user_identity" in source
    assert "invalid_tenant_identity" in source
    assert "empty_content" in source
    assert '"migration_eligible": 0' in source
    assert '"eligibility_status": "unverified_consent_and_identity"' in source
    assert not any(
        phrase in source.lower()
        for phrase in ("delete from public.persona_memory_entries",
                       "insert into public.memory_event",
                       "update public.persona_memory_entries")
    )
