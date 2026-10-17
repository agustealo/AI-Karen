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
        self.projection_target_names = frozenset({"redis", "memory_graph"})

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


@pytest.mark.asyncio
async def test_semantic_metadata_conflict_cannot_reach_neurovault():
    signal = MemorySignal(
        text="Black is my favorite color",
        signal_type="preference",
        confidence=0.98,
        metadata={
            "explicit_user_statement": True,
            "category": "preference",
            "attribute": "favorite_color",
            "normalized_value": "black",
            "cardinality": "singleton",
        },
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(vault, projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        metadata={"cardinality": "set"},
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 0
    assert "formation:metadata_boundary" in result["errors"]
    assert vault.calls == []
    assert projector.calls == []


@pytest.mark.asyncio
async def test_durable_semantics_keep_contextual_scope_separate_from_access_scope():
    signal = MemorySignal(
        text="Bob Marley is my favorite reggae artist",
        signal_type="preference",
        confidence=0.98,
        scope="user",
        metadata={
            "explicit_user_statement": True,
            "category": "preference",
            "attribute": "favorite_artist",
            "normalized_value": "Bob Marley",
            "cardinality": "scoped_singleton",
            "scope": "genre:reggae",
            "facet": "artist",
        },
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(vault, projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        metadata={"request_id": "request-1"},
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    custom = vault.calls[0][0].metadata.custom
    assert custom["signal_semantics"]["scope"] == "genre:reggae"
    assert custom["signal_semantics"]["cardinality"] == "scoped_singleton"
    assert custom["scope"] == "user"
    assert custom["runtime_context"]["request_id"] == "request-1"
    assert projector.calls[0]["signal"].metadata["scope"] == "genre:reggae"


@pytest.mark.asyncio
async def test_missing_durable_event_receipt_does_not_mask_projection_failure():
    signal = MemorySignal(
        text="I prefer concise explanations",
        signal_type="preference",
        confidence=0.95,
    )

    class _EventlessVault(_Vault):
        async def persist(self, entry, *, context):
            self.calls.append((entry, context))
            return VaultWriteReceipt(
                memory_id=entry.id,
                persisted=True,
                version=entry.version,
                metadata={},
            )

    vault = _EventlessVault()
    projector = _Projector()
    result = await _service(vault, projector, signal).process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        correlation_id="test-eventless-receipt",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    assert result["status"] == "degraded"
    assert result["projection_failures"] == 1
    assert "projection:missing_event_id" in result["errors"]
    assert result["receipts"][0]["projection_results"] == {"projection_pipeline": False}
    assert projector.calls == []


def test_projection_target_summary_exposes_only_stage_counts():
    from ai_karen_engine.core.memory.formation.service import (
        _projection_target_health,
    )

    receipts = [
        {
            "memory_id": "private-memory-id",
            "event_id": "private-event-id",
            "projection_results": {"stm": True, "memory_graph": False},
        },
        {
            "memory_id": "other-private-memory-id",
            "event_id": "other-private-event-id",
            "projection_results": {"stm": True, "memory_graph": True},
        },
    ]

    observed = _projection_target_health(
        receipts, allowed_targets=frozenset({"stm", "memory_graph"})
    )

    assert observed == [
        {"target": "memory_graph", "success_count": 1, "failure_count": 1},
        {"target": "stm", "success_count": 2, "failure_count": 0},
    ]
    assert "private" not in str(observed)


def test_projection_target_summary_does_not_expose_unsafe_target_names():
    from ai_karen_engine.core.memory.formation.service import (
        _projection_target_health,
    )

    result = _projection_target_health([
        {"projection_results": {"password=private-secret": False}},
    ])

    assert result == [
        {"target": "unidentified_projection", "success_count": 0, "failure_count": 1},
    ]
    assert "private-secret" not in str(result)


def test_projection_target_summary_rejects_unregistered_but_well_formed_name():
    from ai_karen_engine.core.memory.formation.service import (
        _projection_target_health,
    )

    result = _projection_target_health(
        [{"projection_results": {"some_personal_value": True, "stm": False}}],
        allowed_targets=frozenset({"stm", "memory_graph"}),
    )

    assert result == [
        {"target": "stm", "success_count": 0, "failure_count": 1},
        {"target": "unidentified_projection", "success_count": 1, "failure_count": 0},
    ]
    assert "some_personal_value" not in str(result)


def test_projection_target_summary_retains_internal_pipeline_failures():
    from ai_karen_engine.core.memory.formation.service import (
        _projection_target_health,
    )

    assert _projection_target_health(
        [{"projection_results": {"projection_pipeline": False}}],
        allowed_targets=frozenset({"stm", "memory_graph"}),
    ) == [
        {"target": "projection_pipeline", "success_count": 0, "failure_count": 1},
    ]
