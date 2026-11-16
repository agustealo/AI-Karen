"""KCOG-01B9: admission API only accepts trusted session/RBAC identity.

Dependency overrides isolate *test-only* identity fixtures. Production uses
the canonical get_current_user session-authentication path and RBAC manager.
These tests cannot substitute for real token/session-revocation integration.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.admin.verification_reviews import (
    get_verification_review_workflow,
    router,
)
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.intelligence.ml.verification_review_workflow import (
    VerificationReviewWorkflow,
)
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore
from ai_karen_engine.core.security.auth_config import AuthConfig


TENANT = str(uuid4())
SUBJECT = str(uuid4())
REVIEWER = str(uuid4())
PERMISSION = Permission.VERIFICATION_REVIEW.value


def make_client(user: UserData | None = None, workflow=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/training")
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if workflow is not None:
        app.dependency_overrides[get_verification_review_workflow] = lambda: workflow
    return TestClient(app)


def request_payload():
    return {
        "decision_observation_id": "never-recorded",
        "subject_user_id": SUBJECT,
        "reward": 0.7,
        "verification_needed": True,
    }


def verified_user(*, permissions=None, active=True):
    return UserData(
        user_id=REVIEWER, tenant_id=TENANT,
        roles=["user"],
        permissions=list(permissions if permissions is not None else [PERMISSION]),
        is_active=active, is_verified=True,
    )


def empty_workflow():
    return VerificationReviewWorkflow(
        lineage_store=InMemoryTrajectoryStore(),
        outcome_store=InMemoryOutcomeStore(),
    )


def test_review_endpoint_requires_recognized_canonical_rbac_permission(monkeypatch):
    monkeypatch.setattr(AuthConfig, "should_bypass_auth", classmethod(lambda cls: False))
    assert Permission.VERIFICATION_REVIEW.value == "intelligence.ml.verification_review"

    denied = make_client(verified_user(permissions=[]), empty_workflow())
    response = denied.post("/api/admin/training/verification/reviews/", json=request_payload())
    assert response.status_code == 403

    allowed = make_client(verified_user(), empty_workflow())
    response = allowed.post("/api/admin/training/verification/reviews/", json=request_payload())
    # Permission is real, but the user cannot invent a durable decision ID.
    assert response.status_code == 404
    assert response.json()["detail"] == "Recorded decision unavailable"


def test_review_endpoint_rejects_unverified_or_bypass_identity(monkeypatch):
    monkeypatch.setattr(AuthConfig, "should_bypass_auth", classmethod(lambda cls: True))
    client = make_client(verified_user(), empty_workflow())
    response = client.post("/api/admin/training/verification/reviews/", json=request_payload())
    assert response.status_code == 403

    monkeypatch.setattr(AuthConfig, "should_bypass_auth", classmethod(lambda cls: False))
    client = make_client(verified_user(active=False), empty_workflow())
    response = client.post("/api/admin/training/verification/reviews/", json=request_payload())
    assert response.status_code == 403


def test_review_endpoint_does_not_accept_client_supplied_policy_facts(monkeypatch):
    monkeypatch.setattr(AuthConfig, "should_bypass_auth", classmethod(lambda cls: False))
    client = make_client(verified_user(), empty_workflow())
    forged = {
        **request_payload(),
        "candidate_probabilities": {
            "respond_direct": 0.0, "verify_then_respond": 1.0,
        },
        "behavior_policy_version": "fabricated",
    }
    response = client.post("/api/admin/training/verification/reviews/", json=forged)
    assert response.status_code == 422
    response = client.post("/api/admin/training/verification/reviews/", json={
        **request_payload(), "verification_needed": "yes",
    })
    assert response.status_code == 422
    response = client.post("/api/admin/training/verification/reviews/", json={
        **request_payload(), "reward": "NaN",
    })
    assert response.status_code == 422


def test_route_is_mounted_in_existing_admin_training_owner():
    contents = Path(
        "src/ai_karen_engine/api_routes/admin/training.py"
    ).read_text()
    assert "router.include_router(verification_reviews_router)" in contents
    assert "require_permission(Permission.VERIFICATION_REVIEW)" in Path(
        "src/ai_karen_engine/api_routes/admin/verification_reviews.py"
    ).read_text()


def test_admin_training_import_does_not_eagerly_import_scipy() -> None:
    script = """
import sys
class BlockSciPy:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "scipy" or fullname.startswith("scipy."):
            raise ImportError("SciPy must not be loaded for reviewer ingress")
sys.meta_path.insert(0, BlockSciPy())
from ai_karen_engine.api_routes.admin.training import router
from ai_karen_engine.core.intelligence.ml.policy_evaluation import PolicyObservation
assert PolicyObservation is not None
assert any(
    route.path == "/admin/training/verification/reviews/"
    for route in router.routes
)
assert "scipy" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
