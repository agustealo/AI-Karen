"""Keyed, bounded observations of rows used by the canonical sklearn fit.

This is a worker assertion about fit membership, not an independent source
attestation or a training permission. Never persist original sample IDs, labels,
feature values, source text, HMAC keys, or arbitrary caller-supplied paths.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from ai_karen_engine.core.intelligence.ml.training.datasets import (
    TopologyTrainingExample,
)

_SCHEMA = "kcm-sklearn-fit-observation-v1"
_MAX_MEMBERS = 10_000
_MAX_BYTES = 4 * 1024 * 1024
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_BODY_KEYS = frozenset({
    "schema_version", "engine", "tenant_key", "job_id", "model_id",
    "model_version", "dataset_version", "feature_version", "key_id",
    "seed", "train_count", "holdout_count", "train", "holdout",
    "source_ancestry_verified", "independent_fit_verified",
    "training_evaluation_disjointness_verified", "training_authorized",
    "execution_authorized", "general_skill_certified",
})
_MEMBER_KEYS = frozenset({"member_hmac", "content_hmac"})


@dataclass(frozen=True, slots=True)
class SklearnFitObservationSummary:
    """Integrity-checked, executor-authored observation, not KCM certification."""

    evidence_sha256: str
    train_count: int
    holdout_count: int
    key_id: str
    worker_observation_integrity_verified: bool = True
    training_example_inventory_verified: bool = False
    training_evaluation_disjointness_verified: bool = False
    independent_oracle_verified: bool = False
    training_authorized: bool = False
    execution_authorized: bool = False
    general_skill_certified: bool = False


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _key(key: bytes, key_id: str) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("A host-managed 256-bit observation key is required")
    if (
        not isinstance(key_id, str) or not 1 <= len(key_id) <= 64
        or not all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in key_id)
    ):
        raise ValueError("A valid explicit observation key ID is required")


def _hmac(key: bytes, domain: bytes, value: object) -> str:
    return hmac.new(key, domain + b"\0" + _json_bytes(value), hashlib.sha256).hexdigest()


def _required_string(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= 256


def _members(
    *, examples: Sequence[TopologyTrainingExample],
    indices: Sequence[int], tenant_id: str, key: bytes,
) -> list[dict[str, str]]:
    answer: list[dict[str, str]] = []
    for index in indices:
        if type(index) is not int or not 0 <= index < len(examples):
            raise ValueError("Observed fit index outside loaded examples")
        example = examples[index]
        if not _required_string(example.example_id):
            raise ValueError("Training examples require stable example IDs")
        if not _required_string(example.feature_version):
            raise ValueError("Training examples require a feature version")
        if not isinstance(example.features, dict) or not _required_string(example.target):
            raise ValueError("Training example content contract is invalid")
        identity = (tenant_id, example.example_id)
        payload = (
            tenant_id, example.example_id, example.feature_version,
            example.features, example.target,
        )
        answer.append({
            "member_hmac": _hmac(key, b"kcm.fit.member.v1", identity),
            "content_hmac": _hmac(key, b"kcm.fit.content.v1", payload),
        })
    answer.sort(key=lambda member: member["member_hmac"])
    return answer


def create_sklearn_fit_observation(
    *,
    tenant_id: str,
    job_id: str,
    model_id: str,
    model_version: str,
    dataset_version: str,
    feature_version: str,
    seed: int,
    examples: Sequence[TopologyTrainingExample],
    train_indices: Sequence[int],
    holdout_indices: Sequence[int],
    key_id: str,
    key: bytes,
) -> bytes:
    """Seal exactly the rows selected for a completed model.fit call.

    This must be called by the sklearn executor only after successful fit.
    It does not prove what source generated an example ID or establish that
    an independent benchmark was held out.
    """
    _key(key, key_id)
    if not all(_required_string(value) for value in (
        tenant_id, job_id, model_id, model_version, dataset_version,
        feature_version,
    )) or tenant_id == "default":
        raise ValueError("Complete scoped training identities are required")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("An explicit bounded split seed is required")
    if (
        not 2 <= len(examples) <= _MAX_MEMBERS
        or not train_indices or not holdout_indices
        or len(train_indices) + len(holdout_indices) != len(examples)
    ):
        raise ValueError("A bounded complete fit/holdout partition is required")
    train = _members(
        examples=examples, indices=train_indices, tenant_id=tenant_id, key=key,
    )
    holdout = _members(
        examples=examples, indices=holdout_indices, tenant_id=tenant_id,
        key=key,
    )
    identifiers = [item["member_hmac"] for item in train + holdout]
    if len(set(identifiers)) != len(examples):
        raise ValueError("Repeated example IDs or incomplete fit/holdout membership")
    if any(example.feature_version != feature_version for example in examples):
        raise ValueError("Feature-version drift in observed fit membership")
    body: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "engine": "sklearn",
        "tenant_key": hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16],
        "job_id": job_id,
        "model_id": model_id,
        "model_version": model_version,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "key_id": key_id,
        "seed": seed,
        "train_count": len(train),
        "holdout_count": len(holdout),
        "train": train,
        "holdout": holdout,
        "source_ancestry_verified": False,
        "independent_fit_verified": False,
        "training_evaluation_disjointness_verified": False,
        "training_authorized": False,
        "execution_authorized": False,
        "general_skill_certified": False,
    }
    payload = {**body, "hmac_sha256": _hmac(key, b"kcm.fit.receipt.v1", body)}
    serialized = _json_bytes(payload)
    if len(serialized) > _MAX_BYTES:
        raise ValueError("Training fit observation exceeds bounded size")
    return serialized


def inspect_sklearn_fit_observation(
    encoded: bytes,
    *,
    tenant_id: str,
    job_id: str,
    model_id: str,
    model_version: str,
    dataset_version: str,
    key_id: str,
    key: bytes,
) -> SklearnFitObservationSummary | None:
    """Verify keyed integrity and scoped identity, but never KCM competence."""
    try:
        _key(key, key_id)
        if (
            not isinstance(encoded, bytes)
            or not 0 < len(encoded) <= _MAX_BYTES
            or not all(_required_string(v) for v in (
                tenant_id, job_id, model_id, model_version, dataset_version,
            ))
        ):
            return None
        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != _BODY_KEYS | {"hmac_sha256"}:
            return None
        if _json_bytes(payload) != encoded:
            return None
        if any(payload.get(field) != expected for field, expected in (
            ("schema_version", _SCHEMA),
            ("engine", "sklearn"),
            ("tenant_key", hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]),
            ("job_id", job_id),
            ("model_id", model_id),
            ("model_version", model_version),
            ("dataset_version", dataset_version),
            ("key_id", key_id),
        )):
            return None
        if not _required_string(payload.get("feature_version")):
            return None
        if type(payload.get("seed")) is not int or not 0 <= payload["seed"] <= 2**32 - 1:
            return None
        if any(payload.get(flag) is not False for flag in (
            "source_ancestry_verified", "independent_fit_verified",
            "training_evaluation_disjointness_verified", "training_authorized",
            "execution_authorized", "general_skill_certified",
        )):
            return None
        train, holdout = payload["train"], payload["holdout"]
        if (
            not isinstance(train, list) or not isinstance(holdout, list)
            or not train or not holdout
            or len(train) + len(holdout) > _MAX_MEMBERS
            or type(payload["train_count"]) is not int
            or type(payload["holdout_count"]) is not int
            or payload["train_count"] != len(train)
            or payload["holdout_count"] != len(holdout)
        ):
            return None
        ids: list[str] = []
        for group in (train, holdout):
            previous = ""
            for item in group:
                if (
                    not isinstance(item, dict) or set(item) != _MEMBER_KEYS
                    or any(not isinstance(item[k], str) or not _HEX.fullmatch(item[k])
                           for k in _MEMBER_KEYS)
                ):
                    return None
                member_id = item["member_hmac"]
                if member_id <= previous:
                    return None
                previous = member_id
                ids.append(member_id)
        if len(set(ids)) != len(ids):
            return None
        tag = payload["hmac_sha256"]
        if not isinstance(tag, str) or not _HEX.fullmatch(tag):
            return None
        body = {k: v for k, v in payload.items() if k != "hmac_sha256"}
        if not hmac.compare_digest(
            tag, _hmac(key, b"kcm.fit.receipt.v1", body),
        ):
            return None
        return SklearnFitObservationSummary(
            evidence_sha256=hashlib.sha256(encoded).hexdigest(),
            train_count=len(train),
            holdout_count=len(holdout),
            key_id=key_id,
        )
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError, KeyError):
        return None


__all__ = [
    "SklearnFitObservationSummary", "create_sklearn_fit_observation",
    "inspect_sklearn_fit_observation",
]
