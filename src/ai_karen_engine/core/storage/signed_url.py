"""Signed URL policy.

Centralize temporary download access.
Avoid long-lived signed links acting like permanent public URLs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional


class ArtifactSensitivity(str, Enum):
    ORDINARY = "ordinary"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


@dataclass(frozen=True)
class SignedUrlPolicy:
    default_ttl: timedelta = timedelta(minutes=10)
    maximum_ttl: timedelta = timedelta(minutes=30)
    sensitivity_ttls: dict = field(default_factory=lambda: {
        ArtifactSensitivity.ORDINARY.value: timedelta(minutes=10),
        ArtifactSensitivity.SENSITIVE.value: timedelta(minutes=5),
        ArtifactSensitivity.HIGHLY_SENSITIVE.value: timedelta(minutes=2),
    })
    audit_required: bool = True


DEFAULT_SIGNED_URL_POLICY = SignedUrlPolicy()


def resolve_ttl(policy: SignedUrlPolicy, sensitivity: ArtifactSensitivity) -> timedelta:
    ttl = policy.sensitivity_ttls.get(sensitivity.value, policy.default_ttl)
    if ttl > policy.maximum_ttl:
        return policy.maximum_ttl
    return ttl
