"""Regression proof: caller-supplied source lineage never becomes Vault authority."""

import pytest

from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata
from ai_karen_engine.platform.memory.postgres.vault import (
    NeuroVaultAuthorizationError,
    PostgresNeuroVault,
)


@pytest.mark.parametrize(
    ("lineage_key", "lineage_value"),
    [
        ("source_lineage", None),
        ("source_lineage", {}),
        ("source_lineage", {"authorization_status": "authorized"}),
        ("derived_source_ids", None),
        ("derived_source_ids", []),
        ("derived_source_ids", ["conversation-owned-by-user"]),
    ],
)
def test_public_vault_write_rejects_unattested_lineage(
    monkeypatch: pytest.MonkeyPatch, lineage_key: str, lineage_value: object,
) -> None:
    # Scope and capability are separately tested by their canonical owners.
    # Isolate this pre-DB claim barrier: even an otherwise-authorized write
    # cannot convert mutable metadata into attested source permission.
    monkeypatch.setattr(PostgresNeuroVault, "_require_capability", lambda *args: None)
    monkeypatch.setattr(PostgresNeuroVault, "_validate_entry_scope", lambda *args: None)
    vault = object.__new__(PostgresNeuroVault)
    entry = MemoryEntry(
        id="memory-1",
        content="derived fact",
        metadata=MemoryMetadata(
            tenant_id="tenant-1",
            user_id="user-1",
            custom={lineage_key: lineage_value},
        ),
    )
    with pytest.raises(
        NeuroVaultAuthorizationError, match="trusted persistence attestation"
    ):
        vault._validate_persist_authority(entry, object())


def test_public_vault_write_preserves_non_lineage_memories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PostgresNeuroVault, "_require_capability", lambda *args: None)
    monkeypatch.setattr(PostgresNeuroVault, "_validate_entry_scope", lambda *args: None)
    vault = object.__new__(PostgresNeuroVault)
    entry = MemoryEntry(
        id="direct-memory",
        content="direct fact",
        metadata=MemoryMetadata(
            tenant_id="tenant-1",
            user_id="user-1",
            custom={"persona_id": "Troy"},
        ),
    )
    vault._validate_persist_authority(entry, object())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ordinary", "authorized", "revoked", "foreign", "forged"])
async def test_private_vault_fence_requires_original_scope_and_transaction(mode, monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from ai_karen_engine.core.memory.protocols import VaultContext
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault

    scope = dict(tenant_id="tenant-1", user_id="user-1", session_id="session-1",
                 request_id="req-1", correlation_id="corr-1", conversation_id="conv-1")
    execution = ChatExecutionContext(**scope)
    monkeypatch.setattr(ChatExecutionContext, "has_runtime_attachment_scope", lambda self: True)
    validator = AsyncMock(side_effect=PermissionError("revoked") if mode == "revoked" else None)
    monkeypatch.setattr(ChatExecutionContext, "revalidate_runtime_attachment_session", validator)
    if mode == "foreign":
        execution = ChatExecutionContext(**{**scope, "user_id": "foreign"})
    if mode == "forged":
        execution = SimpleNamespace(**scope)
    context = VaultContext(**scope, private_execution=None if mode == "ordinary" else execution)
    transaction = object()
    if mode in {"revoked", "foreign", "forged"}:
        with pytest.raises(PermissionError, match="attachment_session_denied"):
            await PostgresNeuroVault._require_private_execution(context, transaction)
    else:
        await PostgresNeuroVault._require_private_execution(context, transaction)
    if mode in {"authorized", "revoked"}:
        validator.assert_awaited_once_with(db_session=transaction)
    else:
        validator.assert_not_awaited()
