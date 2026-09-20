from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/services/privacy_compliance.py"
ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/privacy.py"
MIGRATION = ROOT / "supabase/migrations/20260920010000_15_privacy_request_lifecycle.sql"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_source(path: Path, class_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Class {class_name} not found in {path}")


def test_privacy_requests_are_migration_owned_and_self_scoped() -> None:
    migration = _source(MIGRATION)

    assert "CREATE TABLE IF NOT EXISTS public.privacy_requests" in migration
    assert "verification_token_hash char(64) NOT NULL" in migration
    assert "verification_used_at" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "app.current_tenant_id" in migration
    assert "app.current_user_id" in migration
    assert "verification_token text" not in migration.lower()


def test_consumer_privacy_routes_derive_identity_from_auth_context() -> None:
    route = _source(ROUTE)
    export_model = _class_source(ROUTE, "DataExportRequest")
    erasure_model = _class_source(ROUTE, "DataErasureRequest")

    assert "Depends(get_current_user)" in route
    assert "check_scope" not in route
    assert "admin:read" not in route
    assert "admin:write" not in route
    assert "user_id" not in export_model
    assert "tenant_id" not in export_model
    assert "user_id" not in erasure_model
    assert "tenant_id" not in erasure_model
    assert 'estimated_completion="24-48 hours"' not in route


def test_privacy_service_has_no_simulated_erasure_or_retired_vector_store() -> None:
    service = _source(SERVICE)
    forbidden = (
        "Milvus",
        "affected_count = 5",
        "affected_count = 3",
        "affected_count = 8",
        "affected_count = 15",
        "affected_keys = 12",
        "self.privacy_requests: Dict",
        '"mode": "simulated"',
    )
    for token in forbidden:
        assert token not in service

    assert "hmac.compare_digest" in service
    assert "verification_token_hash" in service
    assert "set_config('app.current_tenant_id'" in service
    assert "set_config('app.current_user_id'" in service


def test_memory_erasure_covers_canonical_projection_closure() -> None:
    service = _source(SERVICE)
    required_tables = {
        "memory_items",
        "memory_event",
        "memory_assertion",
        "memory_episode",
        "profile_fact",
        "memory_relation",
        "memory_entity",
        "memory_entity_alias",
        "memory_procedure",
        "reinforcement_event",
        "contradiction_event",
        "projection_status",
        "consent_scope",
    }
    for table in required_tables:
        assert table in service, f"privacy memory closure is missing {table}"

    assert "pgvector embeddings" in service
    assert '"cache_erasure": False' in service
    assert '"audit_log_erasure": False' in service


def test_erasure_modes_and_unsupported_data_fail_closed() -> None:
    from ai_karen_engine.services.privacy_compliance import DataEraser, ErasureType

    assert DataEraser.normalize_data_types(["all"]) == ["memories", "conversations"]
    with pytest.raises(ValueError, match="Unsupported erasure data types"):
        DataEraser.normalize_data_types(["cache"])

    service = _source(SERVICE)
    assert "if erasure_type != ErasureType.HARD_DELETE" in service
    assert "soft_delete and anonymize fail closed" in service


def test_only_real_database_row_counts_are_reported() -> None:
    service = _source(SERVICE)
    eraser = _class_source(SERVICE, "DataEraser")

    assert "_row_count(await session.execute" in eraser
    assert "sum(counts.values())" in eraser
    assert "cascaded_messages" in eraser
    assert "return 5" not in service
    assert "return 3" not in service
    assert "return 8" not in service
    assert "return 12" not in service
    assert "return 15" not in service
