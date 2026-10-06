"""Proactive continuity intelligence."""

from .contracts import (
    ContinuityEvidence,
    NextNeedCandidate,
    ProactiveContinuityRepository,
)
from .service import ProactiveContinuityService

__all__ = [
    "ContinuityEvidence",
    "NextNeedCandidate",
    "ProactiveContinuityRepository",
    "ProactiveContinuityService",
]
