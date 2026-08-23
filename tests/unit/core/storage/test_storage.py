"""Storage contract tests."""

from __future__ import annotations

import uuid
import pytest
from datetime import timedelta

from ai_karen_engine.core.storage.buckets import (
    BucketDefinition,
    TIER_1_BUCKETS,
    private_object_path,
    resolve_bucket,
)
from ai_karen_engine.core.storage.signed_url import (
    ArtifactSensitivity,
    DEFAULT_SIGNED_URL_POLICY,
    resolve_ttl,
)
from ai_karen_engine.core.storage.resumable import ResumableUploadManager, TusSession, TusResult
from ai_karen_engine.core.storage.client import UploadIntent, UploadStatus


def test_tier_1_buckets():
    assert len(TIER_1_BUCKETS) == 3
    names = {b.name for b in TIER_1_BUCKETS}
    assert names == {"artifacts-private", "exports-private", "public-assets"}


def test_private_object_path():
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    aid = uuid.uuid4()
    path = private_object_path(tid, uid, aid)
    assert path == f"tenant/{tid}/user/{uid}/artifact/{aid}/object"


def test_resolve_bucket():
    bucket = resolve_bucket("artifacts-private")
    assert bucket is not None
    assert bucket.public is False


def test_resolve_unknown_bucket():
    assert resolve_bucket("unknown-bucket") is None


def test_resolve_ttl_ordinary():
    ttl = resolve_ttl(DEFAULT_SIGNED_URL_POLICY, ArtifactSensitivity.ORDINARY)
    assert ttl == timedelta(minutes=10)


def test_resumable_upload_manager():
    manager = ResumableUploadManager()
    intent = UploadIntent(bucket="artifacts-private", path="test/object")
    session = manager.create_session(intent)
    assert session.status == UploadStatus.PENDING
    result = manager.complete(session.upload_id, "test/final")
    assert result is not None
    assert result.completed is True
