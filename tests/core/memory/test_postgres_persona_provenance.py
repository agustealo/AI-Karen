"""Prove canonical ledger recall reconstructs attributed persona provenance."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.platform.memory.postgres.recall_retriever import PostgresRecallRetriever


def test_ledger_payload_persona_provenance_restored_without_scope_override():
    tenant, user = str(uuid4()), str(uuid4())
    row = SimpleNamespace(
        assertion_id=uuid4(), event_id=uuid4(), tenant_id=tenant, user_id=user,
        content="User prefers concise explanations", confidence=0.9,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        scope="user", consent_state="granted", valid_from=None, valid_to=None,
    )
    query = MemoryQuery(text="concise explanations", tenant_id=tenant, user_id=user)
    entry = PostgresRecallRetriever._to_entry(
        row, query, query.text,
        {"metadata": {"custom": {"persona_id": "expert", "tenant_id": "spoofed"}}},
    )
    assert entry.metadata.custom["persona_id"] == "expert"
    assert entry.metadata.tenant_id == tenant
    assert entry.metadata.user_id == user


def test_unattributed_ledger_memory_remains_shared():
    tenant, user = str(uuid4()), str(uuid4())
    row = SimpleNamespace(
        assertion_id=uuid4(), event_id=uuid4(), tenant_id=tenant, user_id=user,
        content="Shared fact", confidence=0.8, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc), scope="user", consent_state="granted",
        valid_from=None, valid_to=None,
    )
    query = MemoryQuery(text="Shared fact", tenant_id=tenant, user_id=user)
    entry = PostgresRecallRetriever._to_entry(row, query, query.text, {})
    assert "persona_id" not in entry.metadata.custom


def test_durable_assertion_receipt_uses_canonical_event_columns():
    tenant, user = str(uuid4()), str(uuid4())
    assertion_id, event_id = uuid4(), uuid4()
    row = SimpleNamespace(
        assertion_id=assertion_id,
        event_id=event_id,
        tenant_id=tenant,
        user_id=user,
        content="Derived from external resource",
        confidence=0.8,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        scope="user",
        consent_state="granted",
        valid_from=None,
        valid_to=None,
    )
    query = MemoryQuery(text="external resource", tenant_id=tenant, user_id=user)
    entry = PostgresRecallRetriever._to_entry(
        row,
        query,
        query.text,
        {
            "metadata": {
                "custom": {
                    "source_type": "chat",
                    "source_ref": "spoofed-message",
                    "persona_id": "Troy",
                }
            }
        },
        "web",
        "canonical-external-resource-1",
    )
    assert entry.metadata.custom["persona_id"] == "Troy"
    receipt = entry.metadata.custom["provenance"]
    assert receipt == {
        "store": "postgres",
        "record_type": "memory_assertion",
        "assertion_id": str(assertion_id),
        "event_id": str(event_id),
        "source_type": "web",
        "source_ref": "canonical-external-resource-1",
    }
    assert entry.metadata.tenant_id == tenant
    assert entry.metadata.user_id == user
