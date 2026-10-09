import pytest

from ai_karen_engine.core.memory.formation.evaluator import MemoryFormationEvaluator
from ai_karen_engine.core.memory.formation.service import MemoryFormationService
from ai_karen_engine.core.memory.guards import MemoryOrigin, MemoryTrustProvenance
from ai_karen_engine.core.memory.protocols import VaultWriteReceipt
from ai_karen_engine.core.memory.signals import ExtractionResult, MemorySignal
from ai_karen_engine.core.memory.types import MemoryType


class _Pipeline:
    def __init__(self, signal):
        self.signal = signal

    async def process_text(self, **kwargs):
        return ExtractionResult(signals=[self.signal], status="success")


class _Scorer:
    async def evaluate(self, text, signal_type):
        return {"is_worthy": True, "score": 0.9, "threshold": 0.6}


class _PrivacyClassifier:
    def __init__(self, *, contains_pii=False, pii_types=None):
        self.contains_pii = contains_pii
        self.pii_types = list(pii_types or [])

    def extract_safe_metadata(self, value):
        return {
            "text_length": len(value or ""),
            "word_count": len((value or "").split()),
            "contains_pii": self.contains_pii,
            "pii_types": self.pii_types,
            "pii_count": len(self.pii_types),
        }


class _RejectingVault:
    async def persist(self, entry, *, context):
        raise PermissionError(
            "durable memory operation requires explicit capability: memory.write"
        )


class _Vault:
    def __init__(self):
        self.calls = []

    async def persist(self, entry, *, context):
        self.calls.append((entry, context))
        return VaultWriteReceipt(
            memory_id=entry.id,
            persisted=True,
            version=entry.version,
            metadata={"event_id": "00000000-0000-0000-0000-000000000010"},
        )


class _Projector:
    def __init__(self):
        self.calls = []

    async def project(self, **kwargs):
        self.calls.append(kwargs)
        return {"redis": True, "memory_graph": True}


def _service(vault, projector, signal, *, privacy_classifier=None):
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_Pipeline(signal),
        worthiness_scorer=_Scorer(),
        privacy_classifier=privacy_classifier or _PrivacyClassifier(),
    )
    return MemoryFormationService(
        vault_factory=lambda tenant_id: vault,
        derived_projector=projector,
        evaluator=evaluator,
    )


@pytest.mark.asyncio
async def test_formation_fails_closed_without_memory_write_authority():
    signal = MemorySignal(
        text="Remember that I prefer concise reports",
        signal_type="preference",
        confidence=0.9,
    )
    projector = _Projector()
    service = _service(_RejectingVault(), projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={},
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "memory_write_not_authorized"
    assert result["persisted"] == 0
    assert projector.calls == []


@pytest.mark.asyncio
async def test_explicit_name_only_pii_is_allowed_as_confidential_profile_memory():
    signal = MemorySignal(
        text="My name is Orlando",
        signal_type="identity_fact",
        confidence=0.98,
        metadata={
            "explicit_user_statement": True,
            "semantic_class": "identity",
            "category": "identity",
            "attribute": "preferred_name",
            "normalized_value": "Orlando",
        },
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(
        vault,
        projector,
        signal,
        privacy_classifier=_PrivacyClassifier(
            contains_pii=True,
            pii_types=["name"],
        ),
    )

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["status"] == "success"
    assert result["persisted"] == 1
    entry, _context = vault.calls[0]
    assert entry.memory_type is MemoryType.SEMANTIC
    assert entry.metadata.custom["sensitivity_class"] == "confidential"
    assert entry.metadata.custom["retention_scope"] == "user_profile"
    assert projector.calls[0]["signal"].signal_type == "identity_fact"


@pytest.mark.asyncio
async def test_explicit_relationship_name_is_confidential_profile_memory():
    signal = MemorySignal(
        text="My wife is Ana",
        signal_type="profile_fact",
        confidence=0.98,
        metadata={
            "explicit_user_statement": True,
            "semantic_class": "relationship",
            "category": "relationship",
            "attribute": "relationship.wife",
            "normalized_value": "Ana",
        },
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(
        vault,
        projector,
        signal,
        privacy_classifier=_PrivacyClassifier(
            contains_pii=True,
            pii_types=["name"],
        ),
    )

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["status"] == "success"
    assert result["persisted"] == 1
    entry, _context = vault.calls[0]
    assert entry.memory_type is MemoryType.SEMANTIC
    assert entry.metadata.custom["sensitivity_class"] == "confidential"
    assert entry.metadata.custom["retention_scope"] == "user_profile"
    assert projector.calls[0]["signal"].signal_type == "profile_fact"


@pytest.mark.asyncio
async def test_privacy_sensitive_interaction_is_rejected_before_vault():
    signal = MemorySignal(
        text="My email is user@example.com",
        signal_type="fact",
        confidence=0.9,
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(
        vault,
        projector,
        signal,
        privacy_classifier=_PrivacyClassifier(
            contains_pii=True,
            pii_types=["email"],
        ),
    )

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "privacy_sensitive_interaction"
    assert result["admitted"] == 0
    assert result["persisted"] == 0
    assert vault.calls == []
    assert projector.calls == []


@pytest.mark.asyncio
async def test_neurovault_commit_happens_before_derived_projection():
    signal = MemorySignal(
        text="Use the deployment preflight workflow next time",
        signal_type="workflow",
        confidence=0.9,
        keywords=["deployment", "preflight"],
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(vault, projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        request_id="req-1",
        correlation_id="corr-1",
        session_id="session-1",
        policy_context={"allowed_capabilities": ["memory.write"]},
    )

    assert result["status"] == "success"
    assert result["persisted"] == 1
    assert len(vault.calls) == 1
    entry, context = vault.calls[0]
    assert entry.memory_type is MemoryType.PROCEDURAL
    assert context.request_id == "req-1"
    assert context.correlation_id == "corr-1"
    assert context.policy_context["allowed_capabilities"] == ["memory.write"]
    assert len(projector.calls) == 1
    assert projector.calls[0]["event_id"] == "00000000-0000-0000-0000-000000000010"
    assert projector.calls[0]["memory_id"] == entry.id


@pytest.mark.asyncio
async def test_projection_failure_degrades_but_does_not_deny_committed_truth():
    signal = MemorySignal(
        text="Remember this durable fact",
        signal_type="fact",
        confidence=0.9,
    )
    vault = _Vault()

    class _DegradedProjector(_Projector):
        async def project(self, **kwargs):
            self.calls.append(kwargs)
            return {"redis": True, "memory_graph": False}

    service = _service(vault, _DegradedProjector(), signal)
    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    assert result["status"] == "degraded"
    assert result["projection_failures"] == 1


def test_memory_trust_provenance_defaults_to_derived_inference_origin():
    provenance = MemoryTrustProvenance()

    assert provenance.origin is MemoryOrigin.DERIVED_INFERENCE


class _UnavailableScorer:
    async def evaluate(self, text, signal_type):
        raise RuntimeError("optional salience model unavailable")


@pytest.mark.asyncio
async def test_explicit_origin_survives_unavailable_salience_model():
    signal = MemorySignal(
        text="I'm from Jamaica",
        signal_type="profile_fact",
        confidence=0.98,
        metadata={
            "explicit_user_statement": True,
            "category": "location",
            "attribute": "origin_location",
            "normalized_value": "Jamaica",
        },
    )
    vault = _Vault()
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_Pipeline(signal),
        worthiness_scorer=_UnavailableScorer(),
        privacy_classifier=_PrivacyClassifier(),
    )
    service = MemoryFormationService(
        vault_factory=lambda tenant_id: vault,
        derived_projector=_Projector(),
        evaluator=evaluator,
    )

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    assert vault.calls[0][0].metadata.custom["attribute"] == "origin_location"


@pytest.mark.asyncio
async def test_explicit_location_still_obeys_privacy_restrictions():
    signal = MemorySignal(
        text="I'm from Jamaica and my email is private@example.com",
        signal_type="profile_fact",
        confidence=0.98,
        metadata={
            "explicit_user_statement": True,
            "category": "location",
            "attribute": "origin_location",
            "normalized_value": "Jamaica",
        },
    )
    vault = _Vault()
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_Pipeline(signal),
        worthiness_scorer=_UnavailableScorer(),
        privacy_classifier=_PrivacyClassifier(
            contains_pii=True,
            pii_types=["email"],
        ),
    )
    service = MemoryFormationService(
        vault_factory=lambda tenant_id: vault,
        derived_projector=_Projector(),
        evaluator=evaluator,
    )

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 0
    assert result["reason"] == "privacy_sensitive_interaction"
    assert vault.calls == []


@pytest.mark.asyncio
async def test_mixed_sensitive_message_only_persists_safe_candidate():
    class _TwoSignalPipeline:
        async def process_text(self, **kwargs):
            return ExtractionResult(
                signals=[
                    MemorySignal(
                        text="I'm from Jamaica",
                        signal_type="profile_fact",
                        confidence=0.98,
                        metadata={
                            "explicit_user_statement": True,
                            "category": "location",
                            "attribute": "origin_location",
                            "normalized_value": "Jamaica",
                        },
                    ),
                    MemorySignal(
                        text="My email is private@example.com",
                        signal_type="profile_fact",
                        confidence=0.98,
                        metadata={
                            "explicit_user_statement": True,
                            "category": "contact",
                            "attribute": "email",
                            "normalized_value": "private@example.com",
                        },
                    ),
                ],
                status="success",
            )

    class _CandidatePrivacy:
        def extract_safe_metadata(self, value):
            sensitive = "@" in value
            return {
                "contains_pii": sensitive,
                "pii_types": ["email"] if sensitive else [],
            }

    vault = _Vault()
    projector = _Projector()
    service = MemoryFormationService(
        vault_factory=lambda tenant_id: vault,
        derived_projector=projector,
        evaluator=MemoryFormationEvaluator(
            signal_pipeline=_TwoSignalPipeline(),
            worthiness_scorer=_UnavailableScorer(),
            privacy_classifier=_CandidatePrivacy(),
        ),
    )

    result = await service.process_interaction(
        text="I'm from Jamaica. My email is private@example.com",
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    assert result["admitted"] == 1
    assert len(vault.calls) == 1
    assert vault.calls[0][0].metadata.custom["attribute"] == "origin_location"
    assert len(projector.calls) == 1


@pytest.mark.asyncio
async def test_session_only_self_description_is_not_admitted_for_durable_memory():
    signal = MemorySignal(
        text="I Jamaican",
        signal_type="identity_fact",
        confidence=0.87,
        scope="session",
        metadata={
            "explicit_user_statement": True,
            "semantic_class": "self_description",
            "retention_scope": "session",
            "normalized_value": "Jamaican",
        },
    )
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_Pipeline(signal),
        worthiness_scorer=_Scorer(),
        privacy_classifier=_PrivacyClassifier(),
    )
    evaluation = await evaluator.evaluate(
        text="I Jamaican", tenant_id="tenant-a", user_id="user-1"
    )
    assert evaluation.admitted_count == 0
