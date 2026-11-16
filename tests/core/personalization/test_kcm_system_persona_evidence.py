"""KCM-02B1: prove current system Persona configuration without invented skills."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.persona.contracts import (
    Persona,
    SYSTEM_PERSONAS,
    ToneEnum,
)
from ai_karen_engine.core.personalization.contracts import (
    CapabilityBelief,
    CapabilityBeliefType,
    IdentityDomain,
    IdentityFacet,
    ModelPropertyStatus,
    Provenance,
    SelfModel,
)
from ai_karen_engine.core.personalization.self_model_projection import (
    SelfModelEvidenceAuthority,
    SelfModelEvidenceSubject,
    SelfModelProjectionHealth,
    SelfModelProjector,
)
from ai_karen_engine.core.personalization.system_persona_evidence import (
    CanonicalSystemPersonaEvidenceReader,
    CanonicalSystemPersonaSelfModel,
)

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
async def test_active_system_persona_configuration_is_real_and_advisory() -> None:
    result = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=100,
    ).read(tenant_id=TENANT_A)
    active = [p for p in SYSTEM_PERSONAS if p.is_active and p.is_system_persona]
    assert active
    assert isinstance(result.model, SelfModel)
    assert result.health is SelfModelProjectionHealth.READY
    assert result.verified_claims == 3 * len(active)
    assert result.omitted_claims == 0
    assert len(result.evidence_sha256) == 64
    assert result.model.tenant_id == TENANT_A
    assert not result.model.capability_beliefs
    assert not result.model.principles
    assert not result.model.limits
    assert not result.training_authorized
    assert not result.execution_authorized
    expected = {
        f"persona.system.{p.id}.default_tone": p.default_tone.value
        for p in active
    }
    found = {
        f.key: f.value for f in result.model.identity_facets
    }
    for key, value in expected.items():
        assert found[key] == value
    assert all(
        facet.domain is IdentityDomain.PREFERENCE
        for facet in result.model.identity_facets
    )


@pytest.mark.asyncio
async def test_two_tenants_have_separate_bound_receipts() -> None:
    reader = CanonicalSystemPersonaEvidenceReader()
    ref = "kcm:persona:system:assistant:default_tone"
    first = await reader.verify_many(
        tenant_id=TENANT_A, evidence_refs=(ref,)
    )
    second = await reader.verify_many(
        tenant_id=TENANT_B, evidence_refs=(ref,)
    )
    assert first[ref].tenant_id == TENANT_A
    assert second[ref].tenant_id == TENANT_B
    assert first[ref].subject is SelfModelEvidenceSubject.KAREN_SELF
    assert first[ref].authority is SelfModelEvidenceAuthority.CONFIGURATION
    assert first[ref].claim_sha256 == second[ref].claim_sha256
    assert first[ref].source_revision == second[ref].source_revision

    first_read = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=100
    ).read(tenant_id=TENANT_A)
    other_read = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=100
    ).read(tenant_id=TENANT_B)
    assert first_read.model.tenant_id != other_read.model.tenant_id
    # Identical global Persona configuration still produces distinct
    # tenant-bound lineage digests. The digest is not an RBAC token.
    assert first_read.evidence_sha256 != other_read.evidence_sha256


@pytest.mark.asyncio
async def test_persona_configuration_drift_invalidates_cached_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.personalization import system_persona_evidence as mod

    old = SYSTEM_PERSONAS[0]
    changed = old.model_copy(update={"default_tone": ToneEnum.SERIOUS})
    monkeypatch.setattr(mod, "SYSTEM_PERSONAS", [changed, *SYSTEM_PERSONAS[1:]])

    ref = f"kcm:persona:system:{old.id}:default_tone"
    updated = await CanonicalSystemPersonaEvidenceReader().verify_many(
        tenant_id=TENANT_A, evidence_refs=(ref,),
    )
    assert updated[ref].source_revision
    assert updated[ref].claim_sha256

    def original_provenance() -> Provenance:
        now = datetime.now(timezone.utc)
        return Provenance(
            source="canonical-system-persona",
            confidence=1.0,
            evidence_refs=[ref],
            first_observed_at=now,
            last_confirmed_at=now,
            valid_from=now,
            valid_until=None,
            supersedes=None,
            status=ModelPropertyStatus.CONFIRMED,
        )

    old_claim = IdentityFacet(
        facet_id=ref,
        domain=IdentityDomain.PREFERENCE,
        key=f"persona.system.{old.id}.default_tone",
        value=old.default_tone.value,
        description=f"Built-in {old.id} Persona tone configuration",
        provenance=original_provenance(),
        is_limitation=False,
    )
    now = datetime.now(timezone.utc)
    old_model = SelfModel(
        model_id="old",
        tenant_id=TENANT_A,
        identity_facets=[old_claim],
        principles=[],
        limits=[],
        capability_beliefs=[],
        confidence_summary={},
        created_at=now,
        updated_at=now,
    )
    result = await SelfModelProjector(
        evidence_reader=CanonicalSystemPersonaEvidenceReader(),
        max_evidence_refs=20,
    ).project(model=old_model, tenant_id=TENANT_A)
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert not result.model.identity_facets
    refreshed = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=100
    ).read(tenant_id=TENANT_A)
    assert refreshed.health is SelfModelProjectionHealth.READY
    assert any(
        facet.key == old_claim.key and facet.value == "serious"
        for facet in refreshed.model.identity_facets
    )


@pytest.mark.asyncio
async def test_system_config_receipt_cannot_prove_a_skill() -> None:
    ref = "kcm:persona:system:assistant:default_tone"
    now = datetime.now(timezone.utc)
    original = SelfModel(
        model_id="attempted-escalation",
        tenant_id=TENANT_A,
        identity_facets=[],
        principles=[],
        limits=[],
        capability_beliefs=[CapabilityBelief(
            belief_id="not-proven",
            capability="deployment",
            belief_type=CapabilityBeliefType.STRENGTH,
            description="Can safely deploy production",
            provenance=Provenance(
                source="model-generated",
                confidence=1.0,
                evidence_refs=[ref],
                first_observed_at=now,
                last_confirmed_at=now,
                valid_from=now,
                valid_until=None,
                supersedes=None,
                status=ModelPropertyStatus.CONFIRMED,
            ),
            evidence_refs=[ref],
            is_self_reference=True,
        )],
        confidence_summary={},
        created_at=now,
        updated_at=now,
    )
    result = await SelfModelProjector(
        evidence_reader=CanonicalSystemPersonaEvidenceReader(),
        max_evidence_refs=10,
    ).project(model=original, tenant_id=TENANT_A)
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert not result.model.capability_beliefs


@pytest.mark.asyncio
async def test_user_created_persona_is_not_tenant_wide_karen_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.personalization import system_persona_evidence as mod

    customer = Persona(
        id="private_user_persona",
        name="Private User Persona",
        default_tone=ToneEnum.SERIOUS,
        is_system_persona=False,
    )
    monkeypatch.setattr(mod, "SYSTEM_PERSONAS", [*SYSTEM_PERSONAS, customer])
    result = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=100,
    ).read(tenant_id=TENANT_A)
    assert result.health is SelfModelProjectionHealth.READY
    assert all(
        "private_user_persona" not in facet.key
        for facet in result.model.identity_facets
    )


@pytest.mark.asyncio
async def test_bad_tenant_and_unknown_evidence_not_accepted() -> None:
    reader = CanonicalSystemPersonaEvidenceReader()
    for wrong in ("", "tenant-default", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(ValueError, match="tenant UUID"):
            await reader.verify_many(
                tenant_id=wrong,
                evidence_refs=("kcm:persona:system:assistant:default_tone",),
            )
    unrecognized = await reader.verify_many(
        tenant_id=TENANT_A,
        evidence_refs=("kcm:persona:system:phantom:default_tone",),
    )
    assert unrecognized == {}
    with pytest.raises(ValueError, match="unknown evidence"):
        await reader.verify_many(
            tenant_id=TENANT_A,
            evidence_refs=("memory:personal:secret",),
        )


@pytest.mark.asyncio
async def test_no_false_readiness_when_evidence_budget_insufficient() -> None:
    result = await CanonicalSystemPersonaSelfModel(
        max_evidence_refs=1
    ).read(tenant_id=TENANT_A)
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert result.verified_claims == 0
    assert "self_model_evidence_budget_exceeded" in result.reason_codes


def test_configuration_reader_cannot_be_created_with_invalid_budget() -> None:
    with pytest.raises(ValueError, match="positive max_evidence_refs"):
        CanonicalSystemPersonaSelfModel(max_evidence_refs=0)
