"""Storage bucket topology specification.

Avoid bucket-per-tenant explosion.
Private object path: tenant/{tenant_id}/user/{user_id}/artifact/{artifact_id}/object
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BucketDefinition:
    name: str
    public: bool = False
    allowed_mime_types: tuple = ()
    max_file_size_bytes: int = 0
    description: str = ""


TIER_1_BUCKETS = [
    BucketDefinition(
        name="artifacts-private",
        public=False,
        allowed_mime_types=("*",),
        description="Private user and agent artifacts.",
    ),
    BucketDefinition(
        name="exports-private",
        public=False,
        allowed_mime_types=("application/pdf", "text/csv", "application/json"),
        description="Private exports.",
    ),
    BucketDefinition(
        name="public-assets",
        public=True,
        allowed_mime_types=("image/*", "text/css", "application/javascript"),
        description="Intentionally public shared assets.",
    ),
]


def private_object_path(tenant_id: uuid.UUID, user_id: uuid.UUID, artifact_id: uuid.UUID) -> str:
    return f"tenant/{tenant_id}/user/{user_id}/artifact/{artifact_id}/object"


def resolve_bucket(bucket_name: str) -> Optional[BucketDefinition]:
    for bucket in TIER_1_BUCKETS:
        if bucket.name == bucket_name:
            return bucket
    return None
