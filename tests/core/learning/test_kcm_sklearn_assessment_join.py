"""Adversarial, portable proof of bounded KCM-to-sklearn ID alignment."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest

from ai_karen_engine.learning.kcm_dataset_preflight import KcmDatasetEvidenceError
from ai_karen_engine.learning.kcm_sklearn_assessment_join import (
    KcmSklearnAssessmentJoinError,
    inspect_kcm_sklearn_assessment_join,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal


def uid(n: int) -> str:
    return str(uuid.UUID(int=n))


TENANT, OWNER = uid(1), uid(2)
SOURCE_REVISION = "a" * 64


def fixture() -> tuple[dict[str, Any], bytes, list[dict[str, Any]]]:
    dataset_bytes = b"independent KCM source snapshot for synthetic test only"
    members = []
    for i in range(4):
        members.append({
            "assessment_id": uid(100 + i),
            "source_artifact_id": uid(200 + i),
            "source_revision": SOURCE_REVISION,
            "content_sha256": f"{300 + i:064x}",
            "leakage_group_id": f"group-{i}",
            "split": ("train", "train", "dev", "test")[i],
            "consent_receipt_id": f"consent-{i}",
            "rights_receipt_id": f"rights-{i}",
            "verification_receipt_id": f"verification-{i}",
        })
    manifest = {
        "schema_version": "1.0.0",
        "dataset_id": uid(3), "dataset_version": 1,
        "tenant_id": TENANT, "owner_user_id": OWNER,
        "objective_id": "procedural_skill", "objective_version": "v1",
        "status": "frozen",
        "content_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "selection_recipe": {
            "recipe_id": "coverage", "version": "v1",
            "config_sha256": "f" * 64, "seed": 42,
        },
        "members": members,
        "split_strategy": {
            "name": "grouped", "leakage_group_fields": ["case_id"],
            "test_locked": True,
        },
        "governance": {
            "consent_policy_version": "v1",
            "license_policy_version": "v1",
            "deletion_epoch": 7,
            "revocation_check_at": "2026-11-14T00:00:00Z",
        },
        "created_at": "2026-11-15T00:00:00Z",
        "policy_version": "v1",
    }
    rows = [
        {
            "example_id": members[i]["assessment_id"],
            "feature_version": "v1",
            "features": {"confidence": 0.5 + i / 10, "length": 11 + i},
            "target": "positive" if i else "negative",
        }
        for i in range(2)
    ]
    return manifest, dataset_bytes, rows


def canonical_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                item, ensure_ascii=False, allow_nan=False,
                separators=(",", ":"),
            ) + "\n"
        ).encode("utf-8")
        for item in rows
    )


@dataclass(frozen=True)
class Evidence:
    tenant_id: str
    user_id: str
    source_ref: str
    source_revision: str
    objective: str
    consent_receipt_id: str
    rights_receipt_id: str
    verification_receipt_id: str
    source_valid: bool = True
    current: bool = True
    consent_valid: bool = True
    rights_valid: bool = True
    target_verified: bool = True
    sensitivity_cleared: bool = True
    target_ref: str = "synthetic-reviewed-target"


class Resolver:
    def __init__(self, manifest, *, revoke_after=None, principal=None):
        self.responses = {
            member["source_artifact_id"]: Evidence(
                tenant_id=TENANT, user_id=OWNER,
                source_ref=member["source_artifact_id"],
                source_revision=member["source_revision"],
                objective=manifest["objective_id"],
                consent_receipt_id=member["consent_receipt_id"],
                rights_receipt_id=member["rights_receipt_id"],
                verification_receipt_id=member["verification_receipt_id"],
            )
            for member in manifest["members"]
        }
        self.calls = 0
        self.revoke_after = revoke_after
        self.principal = principal

    async def resolve(self, **kwargs):
        assert kwargs["tenant_id"] == TENANT
        assert kwargs["user_id"] == OWNER
        self.calls += 1
        item = self.responses.get(kwargs["source_ref"])
        if self.principal is not None and self.calls == 5:
            self.principal.session_id = "mutated-session"
        if item is None:
            return None
        if self.revoke_after is not None and self.calls > self.revoke_after:
            from dataclasses import replace

            return replace(item, rights_valid=False)
        return item


class Epoch:
    def __init__(self, *values: int):
        self.values = values or (7,)
        self.calls = 0

    async def current_epoch(self, *, tenant_id, user_id):
        assert tenant_id == TENANT and user_id == OWNER
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TENANT, user_id=OWNER, session_id="authenticated-session",
    )


async def inspect(m=None, data=None, rows=None, *, p=None, resolver=None,
                  epoch=None, raw=None, limit=100):
    if m is None or data is None or rows is None:
        m, data, rows = fixture()
    return await inspect_kcm_sklearn_assessment_join(
        principal=p or principal(), manifest=m,
        governed_dataset_bytes=data,
        training_jsonl_bytes=canonical_jsonl(rows) if raw is None else raw,
        evidence_resolver=resolver or Resolver(m),
        deletion_epoch_reader=epoch or Epoch(),
        max_members=limit,
    )


@pytest.mark.asyncio
async def test_frozen_train_member_alignment_rechecks_live_evidence_no_grants():
    m, data, rows = fixture()
    resolver, epoch = Resolver(m), Epoch()
    result = await inspect(m, data, rows, resolver=resolver, epoch=epoch)
    assert result.frozen_assessment_membership_consistent is True
    assert result.evidence_current_at_inspection is True
    assert result.assessment_count == 2
    assert result.training_row_count == 2
    assert result.training_jsonl_sha256 == hashlib.sha256(
        canonical_jsonl(rows),
    ).hexdigest()
    assert result.governed_dataset_sha256 == hashlib.sha256(data).hexdigest()
    assert len(result.manifest_sha256) == 64
    assert resolver.calls == 8
    assert epoch.calls == 4
    assert result.training_rows_independently_attested is False
    assert result.source_to_feature_transformation_verified is False
    assert result.source_ancestry_verified is False
    assert result.actual_fit_membership_verified is False
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False
    assert result.independent_oracle_verified is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert result.general_skill_certified is False
    assert uid(100) not in repr(result)
    assert "negative" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "dev", "test", "unknown", "duplicate", "missing", "stray", "bad_uuid",
    "non_numeric", "non_finite", "empty_features", "bad_version",
])
async def test_reject_untrusted_training_rows_and_wrong_manifest_split(mutation):
    m, data, rows = fixture()
    rows = deepcopy(rows)
    if mutation == "dev":
        rows[0]["example_id"] = m["members"][2]["assessment_id"]
    elif mutation == "test":
        rows[0]["example_id"] = m["members"][3]["assessment_id"]
    elif mutation == "unknown":
        rows[0]["example_id"] = uid(999)
    elif mutation == "duplicate":
        rows[1]["example_id"] = rows[0]["example_id"]
    elif mutation == "missing":
        rows.pop()
    elif mutation == "stray":
        rows.append({
            **rows[0], "example_id": uid(1000),
        })
    elif mutation == "bad_uuid":
        rows[0]["example_id"] = "untrusted-assessment-label"
    elif mutation == "non_numeric":
        rows[0]["features"]["confidence"] = "untrusted string"
    elif mutation == "non_finite":
        rows[0]["features"]["confidence"] = float("inf")
        # canonical_jsonl itself refuses nonfinite values; supply a JSON
        # fixture with the same shape but a noncanonical infinity token.
        with pytest.raises(ValueError):
            canonical_jsonl(rows)
        return
    elif mutation == "empty_features":
        rows[0]["features"] = {}
    elif mutation == "bad_version":
        rows[0]["feature_version"] = ""
    with pytest.raises(KcmSklearnAssessmentJoinError):
        await inspect(m, data, rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("encoded", [
    b'{"not":"a row"}\n',
    b"[" * 2000 + b"0" + b"]" * 2000 + b"\n",
    b"\xef\xbb\xbf" + b"{}\n",
    b"",
    b"x" * 16,
    b'{"example_id":"abc"}',
])
async def test_malformed_nested_and_noncanonical_jsonl_fails_closed(encoded):
    m, data, rows = fixture()
    with pytest.raises(KcmSklearnAssessmentJoinError):
        await inspect(m, data, rows, raw=encoded)


@pytest.mark.asyncio
async def test_jsonl_importer_byte_contract_is_required():
    m, data, rows = fixture()
    pretty = "\n".join(json.dumps(row, indent=2) for row in rows).encode()
    with pytest.raises(KcmSklearnAssessmentJoinError):
        await inspect(m, data, rows, raw=pretty + b"\n")
    spaced = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    with pytest.raises(KcmSklearnAssessmentJoinError, match="canonical"):
        await inspect(m, data, rows, raw=spaced)


@pytest.mark.asyncio
async def test_false_source_association_does_not_certify_transformation():
    m, data, rows = fixture()
    rows[0]["target"] = "forged-supervision"
    rows[0]["features"]["length"] = 999
    # The manifest's content SHA-256 describes the assessed source, not a
    # canonical feature/target derivation. An ID match must never imply a
    # true source-to-feature link or authorization.
    result = await inspect(m, data, rows)
    assert result.frozen_assessment_membership_consistent
    assert not result.source_to_feature_transformation_verified
    assert not result.training_example_inventory_verified
    assert not result.training_authorized


@pytest.mark.asyncio
async def test_revoked_rights_and_deleted_epoch_fail_closed():
    m, data, rows = fixture()
    with pytest.raises(KcmDatasetEvidenceError):
        await inspect(m, data, rows, resolver=Resolver(m, revoke_after=4))
    with pytest.raises(KcmDatasetEvidenceError):
        await inspect(m, data, rows, epoch=Epoch(7, 7, 7, 8))


@pytest.mark.asyncio
async def test_missing_rights_or_mutated_owner_fails_closed():
    m, data, rows = fixture()
    wrong = principal()
    wrong.user_id = uid(800)
    with pytest.raises(KcmDatasetEvidenceError):
        await inspect(m, data, rows, p=wrong)
    p = principal()
    with pytest.raises(KcmSklearnAssessmentJoinError, match="changed"):
        await inspect(m, data, rows, p=p, resolver=Resolver(m, principal=p))


@pytest.mark.asyncio
async def test_stale_frozen_manifest_content_and_splits_fail_closed():
    m, data, rows = fixture()
    with pytest.raises(KcmDatasetEvidenceError):
        await inspect(m, data + b"touched", rows)
    m, data, rows = fixture()
    m["members"][0]["split"] = "dev"
    with pytest.raises(KcmDatasetEvidenceError):
        await inspect(m, data, rows)


@pytest.mark.asyncio
async def test_no_session_and_bad_size_budget_are_not_positive():
    m, data, rows = fixture()
    p = principal()
    p.session_id = ""
    with pytest.raises(PermissionError):
        await inspect(m, data, rows, p=p)
    with pytest.raises(KcmSklearnAssessmentJoinError, match="budget"):
        await inspect(m, data, rows, limit=1)
    with pytest.raises(KcmSklearnAssessmentJoinError, match="budget"):
        await inspect(m, b"", rows)



@pytest.mark.asyncio
async def test_actual_tenant_immutable_importer_roundtrip_is_accepted(tmp_path):
    """Use the production importer and its real tenant-specific stored bytes."""
    from io import BytesIO

    from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
        import_jsonl_dataset,
        tenant_dataset_directory,
    )

    m, data, rows = fixture()
    raw = canonical_jsonl(rows)
    root = tmp_path / "datasets"
    imported = import_jsonl_dataset(
        source=BytesIO(raw), root=root, tenant_id=TENANT,
        version="frozen-assessment-snapshot-v1",
    )
    imported_path = (
        tenant_dataset_directory(root, TENANT)
        / "frozen-assessment-snapshot-v1.jsonl"
    )
    assert imported["rows"] == 2
    assert imported["sha256"] == hashlib.sha256(raw).hexdigest()
    assert imported_path.read_bytes() == raw
    report = await inspect(
        m, data, rows, raw=imported_path.read_bytes(),
    )
    assert report.training_jsonl_sha256 == imported["sha256"]
    assert report.frozen_assessment_membership_consistent
    assert report.source_to_feature_transformation_verified is False
    assert report.actual_fit_membership_verified is False
    assert report.training_example_inventory_verified is False
    assert report.training_authorized is False

    # Storage isolation does not turn the self-asserted row IDs into rights.
    other_tenant_path = (
        tenant_dataset_directory(root, uid(999))
        / "frozen-assessment-snapshot-v1.jsonl"
    )
    assert not other_tenant_path.exists()



@pytest.mark.asyncio
@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
@pytest.mark.parametrize("field", ["target", "feature_version", "feature_name"])
async def test_real_importer_preserves_unicode_line_separators_inside_records(
    tmp_path, separator, field,
):
    """Only LF divides JSONL records, not Unicode separators in strings."""
    from io import BytesIO

    from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
        import_jsonl_dataset,
        tenant_dataset_directory,
    )

    m, data, rows = fixture()
    for row in rows:
        if field == "feature_name":
            row["features"] = {
                f"confidence{separator}score": 0.5, "length": 11,
            }
        else:
            row[field] = f"valid{separator}value"
    raw = canonical_jsonl(rows)
    root = tmp_path / "tenant-imports"
    imported = import_jsonl_dataset(
        source=BytesIO(raw), root=root, tenant_id=TENANT, version="unicode-v1",
    )
    persisted = (
        tenant_dataset_directory(root, TENANT) / "unicode-v1.jsonl"
    ).read_bytes()
    assert persisted == raw
    assert separator.encode("utf-8") in persisted
    report = await inspect(m, data, rows, raw=persisted)
    assert report.training_row_count == 2
    assert report.training_jsonl_sha256 == imported["sha256"]
    assert report.source_ancestry_verified is False
    assert report.training_authorized is False


@pytest.mark.asyncio
async def test_row_budget_is_checked_before_materializing_all_jsonl_lines():
    m, data, rows = fixture()
    # The first 100 records are legitimate canonical examples. Only the
    # 101st LF record trips the budget; the malformed 100,000-record tail
    # must never be deserialized or materialized as a list of lines.
    valid_rows = [
        {
            "example_id": uid(20_000 + index),
            "feature_version": "v1",
            "features": {"count": index},
            "target": "positive",
        }
        for index in range(100)
    ]
    encoded = canonical_jsonl(valid_rows) + (b"{}\n" * 100_000)
    with pytest.raises(
        KcmSklearnAssessmentJoinError,
        match="training_row_budget_exceeded",
    ):
        await inspect(m, data, rows, raw=encoded, limit=100)


@pytest.mark.asyncio
async def test_one_huge_jsonl_row_is_rejected_before_json_deserialization():
    m, data, rows = fixture()
    huge_row = b'{"target":"' + (b"x" * (1024 * 1024)) + b'"}\n'
    with pytest.raises(
        KcmSklearnAssessmentJoinError,
        match="training_row_size_invalid",
    ):
        await inspect(m, data, rows, raw=huge_row)


@pytest.mark.asyncio
async def test_mutable_manifest_swap_during_async_preflight_cannot_forge_join():
    """An awaited resolver must never switch the assessment snapshot."""
    m, data, rows = fixture()
    unapproved = uid(999)
    rows[0]["example_id"] = unapproved
    original = m["members"][0]["assessment_id"]

    class SwappingResolver(Resolver):
        async def resolve(self, **kwargs):
            # A mutable caller-owned manifest may be altered while preflight
            # awaits a source authority; the snapshot must remain detached.
            if self.calls == 0:
                m["members"][0]["assessment_id"] = unapproved
            elif self.calls == 4:
                m["members"][0]["assessment_id"] = original
            return await super().resolve(**kwargs)

    resolver = SwappingResolver(m)
    with pytest.raises(
        KcmSklearnAssessmentJoinError,
        match="assessment_training_join_mismatch",
    ):
        await inspect(m, data, rows, resolver=resolver)
    assert resolver.calls == 4
    assert m["members"][0]["assessment_id"] == unapproved
