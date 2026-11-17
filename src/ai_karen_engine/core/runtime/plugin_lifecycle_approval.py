"""Immutable action identity for future governed plugin lifecycle approvals.

This type is deliberately not an execution token. Runtime must construct it
from a freshly authenticated principal, installed manifest, and **durable**
lifecycle revision; untrusted chat or UI input can never mint one.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict


_PLUGIN_ID = re.compile(r"[a-z][a-z0-9_-]{0,49}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class PluginLifecycleApprovalScope:
    """Exact global installation transition, principal, and revision snapshot."""

    installation_id: str
    action: str
    manifest_checksum: str
    expected_state: str
    expected_revision: int
    tenant_id: str
    user_id: str
    session_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_id, str)
            or not _PLUGIN_ID.fullmatch(self.installation_id)
            or not isinstance(self.action, str)
            or self.action not in {"enable", "disable"}
            or not isinstance(self.manifest_checksum, str)
            or not _DIGEST.fullmatch(self.manifest_checksum)
            or not isinstance(self.expected_state, str)
            or self.expected_state not in {"enabled", "disabled"}
            or type(self.expected_revision) is not int
            or self.expected_revision < 1
        ):
            raise ValueError("Invalid plugin lifecycle approval target")
        if self.expected_state != ("disabled" if self.action == "enable" else "enabled"):
            raise ValueError("Lifecycle approval must change the observed state")
        for name in ("tenant_id", "user_id", "conversation_id"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError("Invalid lifecycle approval identity")
            try:
                canonical = str(uuid.UUID(value))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("Invalid lifecycle approval identity") from exc
            if value != canonical:
                raise ValueError("Noncanonical lifecycle approval identity")
        if not isinstance(self.session_id, str) or not _SESSION_ID.fullmatch(self.session_id):
            raise ValueError("Invalid lifecycle approval session")

    def require_matching_context(self, context: Any) -> None:
        """Reject an approval prepared for a different authenticated request."""
        if any(
            str(getattr(context, key, "") or "") != getattr(self, key)
            for key in ("tenant_id", "user_id", "session_id", "conversation_id")
        ):
            raise PermissionError("Plugin lifecycle approval identity mismatch")

    def to_record(self) -> Dict[str, Any]:
        """Only bounded non-secret fields may enter durable approval records."""
        return {
            "installation_id": self.installation_id,
            "action": self.action,
            "manifest_checksum": self.manifest_checksum,
            "expected_state": self.expected_state,
            "expected_revision": self.expected_revision,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
        }


__all__ = ["PluginLifecycleApprovalScope"]
