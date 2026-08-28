from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.context.contracts import (
    ContextEvidence,
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)


def test_context_evidence_uses_typed_evidence_domains() -> None:
    now = datetime.now(timezone.utc)
    evidence = ContextEvidence(
        evidence_id="memory-1",
        source=EvidenceSource.MEMORY,
        content="User prefers local-first execution.",
        source_ref="memory-1",
        relevance=0.92,
        confidence=0.88,
        provenance=EvidenceProvenance(
            source_ref="memory-1",
            source_record_id="memory-1",
            resolver_id="runtime.memory",
            resolver_version="1",
            retrieval_method="neuro_recall",
            retrieved_at=now,
            reason_codes=("memory_recall",),
        ),
        temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
        contradiction=EvidenceContradiction(
            status=EvidenceContradictionStatus.NONE,
        ),
        scope=EvidenceScope(
            tenant_id="tenant-1",
            user_id="user-1",
            session_id="session-1",
            conversation_id="conversation-1",
        ),
    )

    assert evidence.provenance.retrieval_method == "neuro_recall"
    assert evidence.temporal.as_of == now
    assert evidence.contradiction.status is EvidenceContradictionStatus.NONE
    assert evidence.scope is not None
    assert evidence.scope.tenant_id == "tenant-1"


def test_evidence_scope_requires_tenant_presence() -> None:
    with pytest.raises(ValueError, match="evidence tenant_id must be present"):
        EvidenceScope(tenant_id="")


def test_legacy_default_tenant_is_recordable_until_ingress_migration() -> None:
    scope = EvidenceScope(tenant_id="default", user_id="user-1")
    assert scope.tenant_id == "default"
