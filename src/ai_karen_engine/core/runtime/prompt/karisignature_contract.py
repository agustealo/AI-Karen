"""KariSignature WS-01: runtime-owned, read-only communication style resolution.

The caller cannot supply a revision as proof. The host's authenticated, scoped
authority must read the CURRENT published revision and authorize each use.
This is expression-only prompt data, never a grant of tools or model selection.
No sample text, private evidence, or client instructions enter this contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from ai_karen_engine.core.runtime.prompt.persona_contract import PersonaAssemblyPolicy


_STYLE_FIELDS = frozenset({
    "style", "tone", "register", "verbosity", "language_style",
})
_TOKEN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_TONES = frozenset({
    "neutral", "warm", "friendly", "formal", "direct", "empathetic",
    "confident", "reserved",
})
_ALLOWED_REGISTERS = frozenset({
    "casual", "conversational", "professional", "executive", "technical",
    "academic", "plain_language",
})
_ALLOWED_VERBOSITY = frozenset({"concise", "balanced", "detailed"})
_ALLOWED_STYLES = frozenset({
    "plain", "narrative", "persuasive", "analytical", "instructional",
    "editorial",
})
_ALLOWED_LANGUAGES = frozenset({
    "en", "en-us", "en-gb", "es", "fr", "de", "pt", "pt-br",
})
_CHOICES = {
    "style": _ALLOWED_STYLES,
    "tone": _ALLOWED_TONES,
    "register": _ALLOWED_REGISTERS,
    "verbosity": _ALLOWED_VERBOSITY,
    "language_style": _ALLOWED_LANGUAGES,
}


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_style_scope")
    try:
        canonical = str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid_style_scope") from exc
    if value != canonical:
        raise ValueError("invalid_style_scope")
    return canonical


@dataclass(frozen=True)
class KariSignatureRequest:
    tenant_id: str
    actor_id: str
    profile_id: str
    purpose: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "actor_id", "profile_id"):
            _uuid(getattr(self, name))
        if not isinstance(self.purpose, str) or not _TOKEN.fullmatch(self.purpose):
            raise ValueError("invalid_style_purpose")
        if not isinstance(self.correlation_id, str) or not 1 <= len(self.correlation_id) <= 128:
            raise ValueError("invalid_style_correlation")


@dataclass(frozen=True)
class KariSignatureRevision:
    profile_id: str
    tenant_id: str
    revision_id: str
    revision_number: int
    state: str
    approved_expression: dict[str, str]
    content_digest: str

    def __post_init__(self) -> None:
        for name in ("profile_id", "tenant_id", "revision_id"):
            _uuid(getattr(self, name))
        if type(self.revision_number) is not int or self.revision_number < 1:
            raise ValueError("invalid_style_revision")
        if self.state != "published":
            raise ValueError("style_not_published")
        if type(self.approved_expression) is not dict or not self.approved_expression:
            raise ValueError("invalid_style_expression")
        if not isinstance(self.content_digest, str) or not _SHA256.fullmatch(self.content_digest):
            raise ValueError("invalid_style_digest")

    @staticmethod
    def digest(expression: dict[str, str]) -> str:
        """Hash canonical expression data; never include samples in the digest."""
        if not isinstance(expression, dict):
            raise ValueError("invalid_style_expression")
        return hashlib.sha256(
            json.dumps(expression, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class KariSignatureResolution:
    profile_id: str
    revision_id: str
    revision_number: int
    content_digest: str
    presentation: dict[str, str]


class KariSignatureAuthority(Protocol):
    """Existing host ownership/policy adapter, not an alternate ACL store."""

    async def read_current_published(
        self, *, tenant_id: str, profile_id: str
    ) -> KariSignatureRevision | None: ...

    async def authorize_use(
        self, *, request: KariSignatureRequest, revision: KariSignatureRevision
    ) -> bool: ...


class KariSignatureResolver:
    """Resolve one host-authorized immutable style to bounded prompt fields.

    The authoritative adapter must check tenant/actor, approved purpose,
    publication, current consent, suspension and revocation at read time.
    The resolver fails closed on missing authority, invalid revisions, drift,
    and any permission or repository error.
    """

    def __init__(self, authority: KariSignatureAuthority) -> None:
        if authority is None:
            raise ValueError("style_authority_required")
        self._authority = authority

    async def resolve(self, request: KariSignatureRequest) -> KariSignatureResolution:
        if not isinstance(request, KariSignatureRequest):
            raise ValueError("invalid_style_request")
        try:
            revision = await self._authority.read_current_published(
                tenant_id=request.tenant_id, profile_id=request.profile_id,
            )
            if revision is None or not isinstance(revision, KariSignatureRevision):
                raise PermissionError("style_unavailable")
            if revision.tenant_id != request.tenant_id or revision.profile_id != request.profile_id:
                raise PermissionError("style_unavailable")
            expression = self._validated_expression(revision.approved_expression)
            if revision.content_digest != KariSignatureRevision.digest(expression):
                raise PermissionError("style_unavailable")
            allowed = await self._authority.authorize_use(request=request, revision=revision)
            if allowed is not True:
                raise PermissionError("style_unavailable")
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise PermissionError("style_unavailable") from exc
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError("style_unavailable") from exc

        # Reuse the existing persona presentation boundary, which cannot
        # elevate style data to system prompt, provider, memory or tools.
        sanitized = PersonaAssemblyPolicy().sanitize_persona(expression)
        if sanitized.rejected_fields or sanitized.ignored_fields or sanitized.data != expression:
            raise PermissionError("style_unavailable")
        return KariSignatureResolution(
            profile_id=revision.profile_id,
            revision_id=revision.revision_id,
            revision_number=revision.revision_number,
            content_digest=revision.content_digest,
            presentation=sanitized.data,
        )

    @staticmethod
    def _validated_expression(expression: dict[str, str]) -> dict[str, str]:
        if type(expression) is not dict or not expression or len(expression) > len(_STYLE_FIELDS):
            raise ValueError("invalid_style_expression")
        validated: dict[str, str] = {}
        for key, value in expression.items():
            if key not in _STYLE_FIELDS or type(value) is not str:
                raise ValueError("invalid_style_expression")
            if value not in _CHOICES[key]:
                raise ValueError("invalid_style_expression")
            validated[key] = value
        return validated


__all__ = [
    "KariSignatureAuthority",
    "KariSignatureRequest",
    "KariSignatureResolution",
    "KariSignatureResolver",
    "KariSignatureRevision",
]
