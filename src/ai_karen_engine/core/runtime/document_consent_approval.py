"""WS-04A9F: immutable first-party document-consent approval scope.

Scope is binding metadata, NEVER an authorization token. RuntimePolicy,
the authenticated bearer-session owner, source repository and the existing
durable ApprovalService must independently verify and consume an actual
author-confirmed approval before the consent issuer can write a receipt.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_ACTIONS = frozenset({"issue", "revoke"})


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_document_consent_scope")
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid_document_consent_scope") from exc
    if parsed != value:
        raise ValueError("invalid_document_consent_scope")
    return parsed


@dataclass(frozen=True, slots=True)
class DocumentConsentApprovalScope:
    tenant_id: str
    author_actor_id: str
    session_id: str
    profile_id: str
    artifact_id: str
    source_sha256: str
    action: str
    analysis_allowed: bool
    style_use_allowed: bool
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "tenant_id", "author_actor_id", "profile_id", "artifact_id"
        ):
            _uuid(getattr(self, name))
        if not isinstance(self.session_id, str) or not _SESSION.fullmatch(
            self.session_id
        ):
            raise ValueError("invalid_document_consent_session")
        if (
            self.action not in _ACTIONS
            or not isinstance(self.source_sha256, str)
            or not _SHA256.fullmatch(self.source_sha256)
            or self.analysis_allowed is not True
            or type(self.style_use_allowed) is not bool
            or not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= datetime.now(timezone.utc)
        ):
            raise ValueError("invalid_document_consent_scope")

    def require_matching_context(self, context: Any) -> None:
        """Require an already-authenticated principal bound to this session.

        This method does not verify session freshness. The host authentication
        middleware MUST revalidate the bearer token and revocation state.
        """
        try:
            principal = context.require_authenticated_user()
        except (AttributeError, PermissionError) as exc:
            raise PermissionError("document_consent_principal_required") from exc
        if (
            str(context.tenant_id) != self.tenant_id
            or str(context.user_id) != self.author_actor_id
            or context.session_id != self.session_id
            or str(principal.tenant_id) != self.tenant_id
            or str(principal.user_id) != self.author_actor_id
        ):
            raise PermissionError("document_consent_scope_mismatch")

    def to_record(self) -> dict[str, str | bool]:
        """Canonical bounded approval binding, without source text or keys."""
        return {
            "tenant_id": self.tenant_id,
            "author_actor_id": self.author_actor_id,
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "artifact_id": self.artifact_id,
            "source_sha256": self.source_sha256,
            "action": self.action,
            "analysis_allowed": self.analysis_allowed,
            "style_use_allowed": self.style_use_allowed,
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
        }

    def fingerprint(self) -> str:
        """Exact immutable source/purpose/session authorization binding."""
        encoded = json.dumps(
            self.to_record(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["DocumentConsentApprovalScope"]
