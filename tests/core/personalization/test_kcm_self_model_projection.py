"""KCM-02A: canonical SelfModel remains advisory and provenance-gated."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    SelfModelEvidenceReceipt,
    SelfModelEvidenceStatus,
    SelfModelProjectionHealth,
    SelfModelProjector,
)

NOW = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
TENANT = "tenant-a"


def provenance(
    ref: str = "config-1",
    *,
    status: ModelPropertyStatus = ModelPropertyStatus.CONFIRMED,
    expires: datetime | None = None,
) -> Provenance:
    return Provenance(
        source="canonical-persona",
        confidence=0.8,
        evidence_refs=[ref],
        first_observed_at=NOW - timedelta(days=5),
        last_confirmed_at=NOW - timedelta(days=1),
        valid_from=NOW - timedelta(days=5),
        valid_until=expires,
        supersedes=None,
        status=status,
    )


def facet(
    ref: str = "config-1", *,
    status: ModelPropertyStatus = ModelPropertyStatus.CONFIRMED,
) -> IdentityFacet:
    return IdentityFacet(
        facet_id="facet-1",
        domain=IdentityDomain.PRINCIPLE,
        key="communication.truthfulness",
        value="reference-only",
        description="Describe only verified capability and provenance",
        provenance=provenance(ref, status=status),
        is_limitation=False,
    )


def belief(
    *,
    ref: str = "review-1",
    status: ModelPropertyStatus = ModelPropertyStatus.CONFIRMED,
    self_reference: bool = True,
) -> CapabilityBelief:
    return CapabilityBelief(
        belief_id="belief-1",
        capability="python-testing",
        belief_type=CapabilityBeliefType.STRENGTH,
        description="Passed independent Python integration tests",
        provenance=provenance(ref, status=status),
        evidence_refs=[ref],
        is_self_reference=self_reference,
    )


def model(
    *,
    principles: list[IdentityFacet] | None = None,
    beliefs: list[CapabilityBelief] | None = None,
    tenant: str = TENANT,
    metadata: dict | None = None,
) -> SelfModel:
    return SelfModel(
        model_id="self-1",
        tenant_id=tenant,
        identity_facets=[],
        capability_beliefs=list(beliefs or []),
        principles=list(principles or []),
        limits=[],
        confidence_summary={},
        created_at=NOW - timedelta(days=3),
        updated_at=NOW,
        metadata=metadata or {},
    )


def receipt(
    ref: str,
    *,
    tenant: str = TENANT,
    status: SelfModelEvidenceStatus = SelfModelEvidenceStatus.ACTIVE,
    authority: SelfModelEvidenceAuthority = (
        SelfModelEvidenceAuthority.CONFIGURATION
    ),
    expires: datetime | None = None,
) -> SelfModelEvidenceReceipt:
    return SelfModelEvidenceReceipt(
        evidence_ref=ref,
        tenant_id=tenant,
        receipt_id=f"receipt-{ref}",
        source_revision="a" * 64,
        status=status,
        authority=authority,
        verified_at=NOW - timedelta(hours=1),
        valid_until=expires,
    )


class EvidenceReader:
    """Synthetic authorized source port; used only for isolated tests."""

    def __init__(
        self,
        receipts: dict[str, SelfModelEvidenceReceipt] | None = None,
        *,
        broken: bool = False,
    ) -> None:
        self.receipts = receipts or {}
        self.broken = broken
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def verify_many(self, *, tenant_id: str, evidence_refs: tuple[str, ...]):
        self.calls.append((tenant_id, evidence_refs))
        if self.broken:
            raise RuntimeError("independent evidence store unavailable")
        return {
            ref: self.receipts[ref]
            for ref in evidence_refs
            if ref in self.receipts
        }


def projector(
    reader: EvidenceReader | None = None, *,
    max_refs: int = 20,
) -> SelfModelProjector:
    return SelfModelProjector(
        evidence_reader=reader or EvidenceReader(), max_evidence_refs=max_refs
    )


@pytest.mark.asyncio
async def test_verified_principle_reuses_canonical_self_model() -> None:
    original = model(principles=[facet()])
    port = EvidenceReader({"config-1": receipt("config-1")})
    result = await projector(port).project(
        model=original, tenant_id=TENANT, at=NOW
    )
    assert isinstance(result.model, SelfModel)
    assert result.health is SelfModelProjectionHealth.READY
    assert len(result.model.principles) == 1
    assert result.model.principles[0].key == "communication.truthfulness"
    assert result.verified_claims == 1
    assert result.omitted_claims == 0
    assert len(result.evidence_sha256) == 64
    assert port.calls == [(TENANT, ("config-1",))]
    assert not result.execution_authorized
    assert not result.training_authorized
    assert result.model is not original
    assert result.model.principles[0] is not original.principles[0]


@pytest.mark.asyncio
async def test_capability_requires_independent_review_and_confirmation() -> None:
    original = model(
        principles=[facet()],
        beliefs=[
            belief(ref="review-1"),
            belief(ref="review-2", status=ModelPropertyStatus.OBSERVED),
        ],
    )
    port = EvidenceReader({
        "config-1": receipt("config-1"),
        "review-1": receipt(
            "review-1",
            authority=SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION,
        ),
        "review-2": receipt(
            "review-2",
            authority=SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION,
        ),
    })
    result = await projector(port).project(
        model=original, tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.DEGRADED
    assert result.verified_claims == 2
    assert result.omitted_claims == 1
    assert [b.capability for b in result.model.capability_beliefs] == [
        "python-testing"
    ]
    assert "self_model_claims_unverified" in result.reason_codes


@pytest.mark.asyncio
async def test_skill_identity_facet_does_not_bypass_independent_evaluation() -> None:
    skill = facet()
    skill.domain = IdentityDomain.SKILL
    skill.key = "codegen.python"
    skill.value = "expert"
    port = EvidenceReader({"config-1": receipt("config-1")})
    result = await projector(port).project(
        model=model(principles=[skill]), tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert not result.model.principles

    port.receipts["config-1"] = receipt(
        "config-1",
        authority=SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION,
    )
    verified = await projector(port).project(
        model=model(principles=[skill]), tenant_id=TENANT, at=NOW
    )
    assert verified.health is SelfModelProjectionHealth.READY


@pytest.mark.asyncio
async def test_capability_cannot_self_certify_from_persona_config() -> None:
    port = EvidenceReader({"review-1": receipt("review-1")})
    result = await projector(port).project(
        model=model(beliefs=[belief()]), tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert not result.model.capability_beliefs
    assert result.omitted_claims == 1


@pytest.mark.asyncio
async def test_user_belief_cannot_appear_as_karen_self_capability() -> None:
    port = EvidenceReader({
        "review-1": receipt(
            "review-1",
            authority=SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION,
        )
    })
    result = await projector(port).project(
        model=model(beliefs=[belief(self_reference=False)]),
        tenant_id=TENANT, at=NOW,
    )
    assert not result.model.capability_beliefs
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    ModelPropertyStatus.RETRACTED,
    ModelPropertyStatus.STALE,
    ModelPropertyStatus.SUPERSEDED,
    ModelPropertyStatus.DISPUTED,
])
async def test_inactive_properties_never_leak(status: ModelPropertyStatus) -> None:
    port = EvidenceReader({"config-1": receipt("config-1")})
    result = await projector(port).project(
        model=model(principles=[facet(status=status)]),
        tenant_id=TENANT, at=NOW,
    )
    assert not result.model.principles
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_revoked_evidence_fences_entire_projection() -> None:
    port = EvidenceReader({
        "config-1": receipt("config-1"),
        "review-1": receipt(
            "review-1", status=SelfModelEvidenceStatus.REVOKED,
            authority=SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION,
        ),
    })
    result = await projector(port).project(
        model=model(principles=[facet()], beliefs=[belief()]),
        tenant_id=TENANT, at=NOW,
    )
    assert result.health is SelfModelProjectionHealth.REVOKED
    assert not result.model.principles
    assert not result.model.capability_beliefs
    assert result.verified_claims == 0
    assert "self_model_evidence_revoked" in result.reason_codes


@pytest.mark.asyncio
async def test_expired_and_cross_tenant_receipts_fail_closed() -> None:
    port = EvidenceReader({
        "config-1": receipt("config-1", tenant="tenant-b"),
    })
    result = await projector(port).project(
        model=model(principles=[facet()]), tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert result.verified_claims == 0

    port.receipts["config-1"] = receipt(
        "config-1", expires=NOW - timedelta(seconds=1)
    )
    expired = await projector(port).project(
        model=model(principles=[facet()]), tenant_id=TENANT, at=NOW
    )
    assert expired.health is SelfModelProjectionHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_missing_authority_returns_unavailable_not_success() -> None:
    port = EvidenceReader(broken=True)
    result = await projector(port).project(
        model=model(principles=[facet()]), tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert result.verified_claims == 0
    assert result.evidence_sha256 == ""
    assert "self_model_evidence_unavailable" in result.reason_codes


@pytest.mark.asyncio
async def test_unknown_evidence_and_no_evidence_are_not_verified() -> None:
    port = EvidenceReader()
    result = await projector(port).project(
        model=model(principles=[facet()]), tenant_id=TENANT, at=NOW
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert result.omitted_claims == 1
    assert result.evidence_sha256 == ""

    no_evidence = await projector(port).project(
        model=model(), tenant_id=TENANT, at=NOW
    )
    assert no_evidence.health is SelfModelProjectionHealth.UNAVAILABLE


@pytest.mark.asyncio
async def test_wrong_tenant_or_user_specific_payload_rejected_before_read() -> None:
    port = EvidenceReader({"config-1": receipt("config-1")})
    with pytest.raises(PermissionError, match="tenant scope"):
        await projector(port).project(
            model=model(tenant="tenant-b", principles=[facet()]),
            tenant_id=TENANT, at=NOW,
        )
    with pytest.raises(PermissionError, match="user-scoped"):
        await projector(port).project(
            model=model(
                principles=[facet()],
                metadata={"user_id": "another-user"},
            ), tenant_id=TENANT, at=NOW,
        )
    assert port.calls == []


@pytest.mark.asyncio
async def test_evidence_budget_blocks_before_expensive_query() -> None:
    port = EvidenceReader({"config-1": receipt("config-1")})
    result = await projector(port, max_refs=1).project(
        model=model(
            principles=[facet()],
            beliefs=[belief()],
        ), tenant_id=TENANT, at=NOW,
    )
    assert result.health is SelfModelProjectionHealth.UNAVAILABLE
    assert "self_model_evidence_budget_exceeded" in result.reason_codes
    assert port.calls == []


@pytest.mark.asyncio
async def test_evidence_digest_is_deterministic_and_no_model_mutation() -> None:
    original = model(principles=[facet()])
    port = EvidenceReader({"config-1": receipt("config-1")})
    first = await projector(port).project(
        model=original, tenant_id=TENANT, at=NOW
    )
    second = await projector(port).project(
        model=original, tenant_id=TENANT, at=NOW
    )
    assert first.evidence_sha256 == second.evidence_sha256
    first.model.principles[0].description = "modified locally"
    assert original.principles[0].description != "modified locally"


def test_verifier_and_budget_must_be_explicit() -> None:
    with pytest.raises(ValueError, match="trusted evidence reader"):
        SelfModelProjector(evidence_reader=None, max_evidence_refs=10)
    with pytest.raises(ValueError, match="positive max_evidence_refs"):
        SelfModelProjector(evidence_reader=EvidenceReader(), max_evidence_refs=0)
