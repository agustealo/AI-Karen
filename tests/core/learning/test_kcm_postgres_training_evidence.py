"""KCM does not treat memory consent/retention as training authorization."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.echocore.postgres_training_evidence import (
    PostgresTrainingEvidenceResolver,
)
from ai_karen_engine.echocore.training_admission import (
    TrainingAdmissionEvaluator,
    TrainingAdmissionPolicy,
    TrainingAdmissionStatus,
)

TENANT = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
USER = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
SOURCE = str(uuid.UUID("33333333-3333-4333-8333-333333333333"))
CONSENT = str(uuid.UUID("44444444-4444-4444-8444-444444444444"))
REVISION = "a" * 64


@dataclass
class MemoryArtifact:
    artifact_id: str = SOURCE
    tenant_id: str = TENANT
    user_id: str = USER
    privacy_tags: tuple[str, ...] = ()
    training_eligibility: str = "review"

    @property
    def metadata(self) -> dict[str, str]:
        return {"source_ref": self.artifact_id, "source_revision": REVISION}


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class Session:
    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.calls = 0
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> Result:
        self.statements.append(str(statement))
        value = self.values[self.calls]
        self.calls += 1
        return Result(value)


def factory_for(values: list[Any]) -> tuple[Any, Session, list[dict[str, str]]]:
    session = Session(values)
    scopes: list[dict[str, str]] = []

    @asynccontextmanager
    async def transaction(**scope: str):
        scopes.append(scope)
        yield session

    return transaction, session, scopes


def event(*, sensitivity: str = "normal", digest: str = REVISION) -> Any:
    return SimpleNamespace(payload_hash=digest, sensitivity_class=sensitivity)


def consent(granted: bool = True, revoked: bool = False) -> Any:
    return SimpleNamespace(
        scope_id=uuid.UUID(CONSENT), is_granted=granted,
        revoked_at="2026-11-16" if revoked else None,
    )


@pytest.mark.asyncio
async def test_source_requires_real_owner_scope_and_payload_digest() -> None:
    transaction, session, scopes = factory_for([event(), None, consent()])
    result = await PostgresTrainingEvidenceResolver(
        transaction_factory=transaction
    ).resolve(
        tenant_id=TENANT, user_id=USER, source_ref=SOURCE,
        source_revision=REVISION, objective="procedural_skill",
    )
    assert result is not None and result.source_valid
    assert result.consent_valid and result.consent_receipt_id == CONSENT
    assert not result.rights_valid and not result.target_verified
    assert result.verification_receipt_id == ""
    assert scopes == [{"tenant_id": TENANT, "user_id": USER}]
    assert session.calls == 3
    assert "memory_event" in session.statements[0]
    assert "consent_scope" in session.statements[2]
    assert "kcm.training" not in session.statements[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [None, consent(False), consent(True, True)])
async def test_missing_denied_or_revoked_training_consent(grant: Any) -> None:
    transaction, _, _ = factory_for([event(), None, grant])
    proof = await PostgresTrainingEvidenceResolver(
        transaction_factory=transaction
    ).resolve(
        tenant_id=TENANT, user_id=USER, source_ref=SOURCE,
        source_revision=REVISION, objective="procedural_skill",
    )
    assert proof is not None and not proof.consent_valid
    assert not proof.consent_receipt_id


@pytest.mark.asyncio
async def test_superseded_source_and_sensitive_memory_not_training_ready() -> None:
    transaction, _, _ = factory_for([event(sensitivity="confidential"), uuid.uuid4(), consent()])
    proof = await PostgresTrainingEvidenceResolver(
        transaction_factory=transaction
    ).resolve(
        tenant_id=TENANT, user_id=USER, source_ref=SOURCE,
        source_revision=REVISION, objective="procedural_skill",
    )
    assert proof is not None and not proof.current
    assert not proof.sensitivity_cleared


@pytest.mark.asyncio
async def test_bad_hash_or_foreign_scope_does_not_query_db() -> None:
    transaction, session, _ = factory_for([])
    resolver = PostgresTrainingEvidenceResolver(transaction_factory=transaction)
    for payload in (
        dict(tenant_id="tenant-other", user_id=USER, source_ref=SOURCE, source_revision=REVISION),
        dict(tenant_id=TENANT, user_id=USER, source_ref=SOURCE, source_revision="x"),
        dict(tenant_id=TENANT, user_id=USER, source_ref=SOURCE, source_revision=REVISION, objective="unsupported"),
    ):
        payload.setdefault("objective", "procedural_skill")
        assert await resolver.resolve(**payload) is None
    assert session.calls == 0


@pytest.mark.asyncio
async def test_stale_digest_fails_closed() -> None:
    transaction, session, _ = factory_for([event(digest="b" * 64)])
    proof = await PostgresTrainingEvidenceResolver(
        transaction_factory=transaction
    ).resolve(
        tenant_id=TENANT, user_id=USER, source_ref=SOURCE,
        source_revision=REVISION, objective="procedural_skill",
    )
    assert proof is None and session.calls == 1


@pytest.mark.asyncio
async def test_current_memory_and_consent_still_cannot_approve_training() -> None:
    transaction, _, _ = factory_for([event(), None, consent()])
    evaluator = TrainingAdmissionEvaluator(
        policy=TrainingAdmissionPolicy(enabled=True),
        evidence_resolver=PostgresTrainingEvidenceResolver(
            transaction_factory=transaction
        ),
    )
    result = await evaluator.evaluate(MemoryArtifact(), objective="procedural_skill")
    assert result.status is TrainingAdmissionStatus.POLICY_BLOCKED
    assert result.reason_codes == ("training_rights_missing",)
