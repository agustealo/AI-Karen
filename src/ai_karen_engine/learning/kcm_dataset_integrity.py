"""Immutable KCM dataset-manifest integrity inspection, not training approval.

This pure helper belongs under the canonical learning dataset domain. It checks
structural consistency and hashes for a manifest and its actual dataset bytes.
It cannot verify consent, rights, labels, membership or tenant ownership by
itself. Those require separate governed authorities immediately before any
training run or model promotion.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SPLITS = {"train": 0, "dev": 1, "test": 2}
_MEMBER_KEYS = frozenset({
    "assessment_id", "source_artifact_id", "source_revision",
    "content_sha256", "leakage_group_id", "split", "consent_receipt_id",
    "rights_receipt_id", "verification_receipt_id",
})
_TOP_KEYS = frozenset({
    "schema_version", "dataset_id", "dataset_version", "tenant_id",
    "owner_user_id", "objective_id", "objective_version", "status",
    "content_sha256", "selection_recipe", "members", "split_strategy",
    "governance", "policy_version", "created_at", "model_compatibility",
})


class KcmManifestIntegrityError(ValueError):
    """A frozen manifest is malformed, inconsistent, or stale."""


def _strict_mapping(value: Any, *, keys: frozenset[str], required: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) - keys or required - set(value):
        raise KcmManifestIntegrityError(f"{name} keys invalid")
    return value


@dataclass(frozen=True, slots=True)
class KcmManifestIntegrityReport:
    """Verified structural integrity only, never training eligibility."""

    manifest_sha256: str
    dataset_sha256: str
    member_count: int
    group_count: int
    train_count: int
    dev_count: int
    test_count: int
    deletion_epoch: int
    training_authorized: bool = False


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KcmManifestIntegrityError(f"{field} must be a nonempty string")
    return value


def _required_uuid(value: Any, field: str) -> str:
    value = _required_text(value, field)
    try:
        identifier = uuid.UUID(value)
    except ValueError as exc:
        raise KcmManifestIntegrityError(f"{field} must be a UUID") from exc
    if str(identifier) != value or identifier.int == 0:
        raise KcmManifestIntegrityError(f"{field} must be non-nil canonical UUID")
    return value


def _required_hash(value: Any, field: str) -> str:
    value = _required_text(value, field)
    if _HASH.fullmatch(value) is None:
        raise KcmManifestIntegrityError(f"{field} must be lowercase SHA-256")
    return value


def _require_datetime(value: Any, field: str) -> datetime:
    value = _required_text(value, field)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KcmManifestIntegrityError(f"{field} is not ISO-8601") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise KcmManifestIntegrityError(f"{field} must include timezone")
    return stamp


def inspect_kcm_dataset_manifest(
    manifest: Mapping[str, Any],
    *,
    dataset_bytes: bytes,
    current_deletion_epoch: int,
) -> KcmManifestIntegrityReport:
    """Inspect a frozen manifest with bytes and a trusted deletion epoch.

    The caller MUST obtain current_deletion_epoch from its authorized
    tenant-scoped governance store, not from the manifest or client metadata.
    Passing this method does not authorize training or indicate that receipts
    are valid. A trainer must recheck source, consent, rights, outcomes and
    revocation at training start and promotion through their existing owners.
    """
    if not isinstance(manifest, Mapping):
        raise KcmManifestIntegrityError("manifest must be a mapping")
    unknown = set(manifest) - _TOP_KEYS
    missing = (_TOP_KEYS - {"model_compatibility"}) - set(manifest)
    if unknown or missing:
        raise KcmManifestIntegrityError("manifest keys invalid")
    if manifest["schema_version"] != "1.0.0" or manifest["status"] != "frozen":
        raise KcmManifestIntegrityError("only frozen KCM v1 manifests are inspectable")
    _required_uuid(manifest["dataset_id"], "dataset_id")
    _required_uuid(manifest["tenant_id"], "tenant_id")
    _required_uuid(manifest["owner_user_id"], "owner_user_id")
    if type(manifest["dataset_version"]) is not int or manifest["dataset_version"] < 1:
        raise KcmManifestIntegrityError("invalid dataset version")
    for field in ("objective_id", "objective_version", "policy_version"):
        _required_text(manifest[field], field)
    created = _require_datetime(manifest["created_at"], "created_at")
    if not isinstance(dataset_bytes, bytes):
        raise KcmManifestIntegrityError("actual dataset bytes are required")
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    if _required_hash(manifest["content_sha256"], "content_sha256") != digest:
        raise KcmManifestIntegrityError("dataset content digest mismatch")

    governance = _strict_mapping(
        manifest["governance"],
        keys=frozenset({"consent_policy_version", "license_policy_version", "deletion_epoch", "revocation_check_at"}),
        required=frozenset({"consent_policy_version", "license_policy_version", "deletion_epoch", "revocation_check_at"}),
        name="governance",
    )
    for field in ("consent_policy_version", "license_policy_version"):
        _required_text(governance.get(field), field)
    epoch = governance.get("deletion_epoch")
    if type(epoch) is not int or epoch < 0:
        raise KcmManifestIntegrityError("invalid deletion epoch")
    if type(current_deletion_epoch) is not int or epoch != current_deletion_epoch:
        raise KcmManifestIntegrityError("manifest deletion epoch is stale")
    rechecked = _require_datetime(governance.get("revocation_check_at"), "revocation_check_at")
    if rechecked > created:
        raise KcmManifestIntegrityError("revocation check after dataset freeze")

    strategy = _strict_mapping(
        manifest["split_strategy"],
        keys=frozenset({"name", "leakage_group_fields", "test_locked"}),
        required=frozenset({"name", "leakage_group_fields", "test_locked"}),
        name="split_strategy",
    )
    if strategy.get("test_locked") is not True:
        raise KcmManifestIntegrityError("frozen test split is not locked")
    _required_text(strategy.get("name"), "split_strategy.name")
    fields = strategy.get("leakage_group_fields")
    if not isinstance(fields, list) or not fields or not all(
        isinstance(field, str) and field.strip() for field in fields
    ):
        raise KcmManifestIntegrityError("leakage group criteria required")

    recipe = _strict_mapping(
        manifest["selection_recipe"],
        keys=frozenset({"recipe_id", "version", "config_sha256", "seed"}),
        required=frozenset({"recipe_id", "version", "config_sha256", "seed"}),
        name="selection_recipe",
    )
    if "model_compatibility" in manifest:
        model = _strict_mapping(
            manifest["model_compatibility"],
            keys=frozenset({"base_model_id", "tokenizer_revision", "chat_template_sha256"}),
            required=frozenset(),
            name="model_compatibility",
        )
        for field in ("base_model_id", "tokenizer_revision"):
            if field in model:
                _required_text(model[field], field)
        if "chat_template_sha256" in model:
            _required_hash(model["chat_template_sha256"], "chat_template_sha256")
    _required_text(recipe.get("recipe_id"), "recipe_id")
    _required_text(recipe.get("version"), "recipe.version")
    _required_hash(recipe.get("config_sha256"), "recipe.config_sha256")
    if type(recipe.get("seed")) is not int or recipe["seed"] < 0:
        raise KcmManifestIntegrityError("recipe seed invalid")

    members = manifest["members"]
    if not isinstance(members, list) or not members:
        raise KcmManifestIntegrityError("frozen dataset requires members")
    member_keys: set[str] = set()
    source_revisions: set[tuple[str, str]] = set()
    group_split: dict[str, str] = {}
    split_counts = {split: 0 for split in _SPLITS}
    order: list[tuple[int, str, str, str]] = []
    for member in members:
        if not isinstance(member, Mapping) or set(member) != _MEMBER_KEYS:
            raise KcmManifestIntegrityError("member fields incomplete or unexpected")
        assessment_id = _required_uuid(member["assessment_id"], "assessment_id")
        source = _required_text(member["source_artifact_id"], "source_artifact_id")
        revision = _required_hash(member["source_revision"], "source_revision")
        _required_hash(member["content_sha256"], "member.content_sha256")
        group = _required_text(member["leakage_group_id"], "leakage_group_id")
        split = member["split"]
        if not isinstance(split, str) or split not in _SPLITS:
            raise KcmManifestIntegrityError("invalid split")
        for field in ("consent_receipt_id", "rights_receipt_id", "verification_receipt_id"):
            _required_text(member[field], field)
        if assessment_id in member_keys or (source, revision) in source_revisions:
            raise KcmManifestIntegrityError("duplicate assessment or source revision")
        member_keys.add(assessment_id)
        source_revisions.add((source, revision))
        previous = group_split.setdefault(group, split)
        if previous != split:
            raise KcmManifestIntegrityError("leakage group appears in multiple splits")
        order.append((_SPLITS[split], group, source, assessment_id))
        split_counts[split] += 1
    if order != sorted(order):
        raise KcmManifestIntegrityError("membership must be in canonical order")
    try:
        raw = json.dumps(
            dict(manifest), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise KcmManifestIntegrityError("manifest is not canonical JSON") from exc
    return KcmManifestIntegrityReport(
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        dataset_sha256=digest,
        member_count=len(members), group_count=len(group_split),
        train_count=split_counts["train"], dev_count=split_counts["dev"],
        test_count=split_counts["test"], deletion_epoch=epoch,
    )


__all__ = [
    "KcmManifestIntegrityError", "KcmManifestIntegrityReport",
    "inspect_kcm_dataset_manifest",
]
