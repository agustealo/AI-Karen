"""WS-03A: consent-gated, source-only KariSignature analysis proposals.

Samples are processed in memory after an external, current provenance and
consent decision. This service neither persists samples nor publishes styles.
The existing lightweight NLPStyleAnalyzer supplies weak, explainable signals;
no inferred value is treated as an approved communication identity.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass
from typing import Protocol

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
)
from ai_karen_engine.services.formatting.nlp_style_analyzer import (
    NLPStyleAnalyzer,
)

_MAX_SAMPLE_BYTES = 16_384
_MIN_WORDS = 20
_MAX_WORDS = 2_000


def _canonical_uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_style_sample")
    try:
        canonical = str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid_style_sample") from exc
    if canonical != value:
        raise ValueError("invalid_style_sample")
    return canonical


@dataclass(frozen=True)
class KariSignatureSample:
    """An explicitly supplied, bounded source, not a persistence receipt."""

    tenant_id: str
    actor_id: str
    profile_id: str
    sample_id: str
    source_ref: str
    content: str
    digest: str

    def __post_init__(self) -> None:
        for field in ("tenant_id", "actor_id", "profile_id", "sample_id"):
            _canonical_uuid(getattr(self, field))
        if (
            not isinstance(self.source_ref, str)
            or not 1 <= len(self.source_ref) <= 160
            or not all(
                ch.isascii() and (ch.isalnum() or ch in "-_:/")
                for ch in self.source_ref
            )
        ):
            raise ValueError("invalid_style_sample")
        if not isinstance(self.content, str):
            raise ValueError("invalid_style_sample")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in self.content):
            raise ValueError("invalid_style_sample")
        size = len(self.content.encode("utf-8"))
        if size == 0 or size > _MAX_SAMPLE_BYTES:
            raise ValueError("invalid_style_sample")
        if (
            not isinstance(self.digest, str)
            or len(self.digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.digest)
            or self.digest != self.content_digest(self.content)
        ):
            raise ValueError("invalid_style_sample")

    @staticmethod
    def content_digest(content: str) -> str:
        if not isinstance(content, str):
            raise ValueError("invalid_style_sample")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class KariSignatureSampleAuthority(Protocol):
    """Host permission/provenance owner must check live consent and source rights.

    A supplied source_ref or digest is not proof of ownership. The authority
    must verify the authenticated actor, tenant, profile, purpose and source,
    active permission and sample-specific consent at execution time.
    """

    async def authorize_analysis(
        self, *, request: KariSignatureRequest, sample: KariSignatureSample
    ) -> bool: ...


@dataclass(frozen=True)
class KariSignatureStyleProposal:
    """Unpublished hint, not an identity, preference, consent or grant."""

    profile_id: str
    sample_id: str
    source_digest: str
    word_count: int
    analysis_status: str
    suggested_tone: str | None
    verbosity_indicator: float | None
    approved: bool = False


class KariSignatureSampleAnalyzer:
    """Use the existing analyzer only after a real host-owned source decision."""

    def __init__(
        self,
        authority: KariSignatureSampleAuthority,
        analyzer: NLPStyleAnalyzer | None = None,
    ) -> None:
        if authority is None:
            raise ValueError("style_sample_authority_required")
        self._authority = authority
        self._analyzer = analyzer if analyzer is not None else NLPStyleAnalyzer()

    async def propose(
        self,
        *, request: KariSignatureRequest, sample: KariSignatureSample,
    ) -> KariSignatureStyleProposal:
        if not isinstance(request, KariSignatureRequest) or not isinstance(
            sample, KariSignatureSample
        ):
            raise ValueError("invalid_style_sample_request")
        if (
            request.tenant_id != sample.tenant_id
            or request.actor_id != sample.actor_id
            or request.profile_id != sample.profile_id
        ):
            raise PermissionError("style_sample_unavailable")

        try:
            permitted = await self._authority.authorize_analysis(
                request=request, sample=sample
            )
        except Exception:
            raise PermissionError("style_sample_unavailable") from None
        if permitted is not True:
            raise PermissionError("style_sample_unavailable")

        words = sample.content.split()
        count = len(words)
        if count < _MIN_WORDS:
            return KariSignatureStyleProposal(
                profile_id=sample.profile_id,
                sample_id=sample.sample_id,
                source_digest=sample.digest,
                word_count=count,
                analysis_status="insufficient_evidence",
                suggested_tone=None,
                verbosity_indicator=None,
            )
        if count > _MAX_WORDS:
            raise ValueError("style_sample_too_many_words")

        try:
            raw = self._analyzer.analyze_style(sample.content)
            tone = getattr(raw, "tone")
            verbosity = getattr(raw, "verbosity")
            if tone not in ("neutral", "friendly"):
                raise ValueError("invalid_style_analysis")
            if (
                type(verbosity) not in (int, float)
                or not math.isfinite(verbosity)
                or not 0 <= verbosity <= 1
            ):
                raise ValueError("invalid_style_analysis")
        except Exception:
            # Do not chain private analyzer content or backend details into
            # surfaced errors or ordinary telemetry.
            raise RuntimeError("style_sample_analysis_unavailable") from None

        return KariSignatureStyleProposal(
            profile_id=sample.profile_id,
            sample_id=sample.sample_id,
            source_digest=sample.digest,
            word_count=count,
            analysis_status="heuristic_proposal_only",
            suggested_tone=tone,
            verbosity_indicator=float(verbosity),
        )


__all__ = [
    "KariSignatureSample",
    "KariSignatureSampleAnalyzer",
    "KariSignatureSampleAuthority",
    "KariSignatureStyleProposal",
]
