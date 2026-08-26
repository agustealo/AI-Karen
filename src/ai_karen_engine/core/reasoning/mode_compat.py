"""Central compatibility normalization for legacy reasoning-mode values.

Canonical callers should send values from ``ReasoningMode``. This shim exists
only while older Runtime/ChatRuntime producers still emit depth/capability words
such as ``deep``, ``reasoning``, and ``synthesis``.

Important: generic depth/capability aliases NEVER opt a request into
``soft_exploration``. Soft Reasoning must be explicitly selected by CORTEX and
authorized by RuntimePolicy.

Sunset: remove legacy aliases after ChatRuntime and all external producers emit
canonical ``reasoning_modes`` directly.
"""

from __future__ import annotations

from collections.abc import Iterable

from ai_karen_engine.core.reasoning.contracts import ReasoningMode

CANONICAL_REASONING_MODES = frozenset(mode.value for mode in ReasoningMode)

_LEGACY_ALIASES: dict[str, tuple[str, ...]] = {
    "reasoning": (
        ReasoningMode.EVIDENCE_SYNTHESIS.value,
        ReasoningMode.VERIFICATION.value,
        ReasoningMode.REFINEMENT.value,
        ReasoningMode.METACOGNITION.value,
    ),
    "deep": (
        ReasoningMode.EVIDENCE_SYNTHESIS.value,
        ReasoningMode.VERIFICATION.value,
        ReasoningMode.REFINEMENT.value,
        ReasoningMode.METACOGNITION.value,
    ),
    "standard": (ReasoningMode.EVIDENCE_SYNTHESIS.value,),
    "light": (ReasoningMode.EVIDENCE_SYNTHESIS.value,),
    "synthesis": (ReasoningMode.EVIDENCE_SYNTHESIS.value,),
}


def normalize_reasoning_modes(
    values: Iterable[str],
    *,
    allow_legacy: bool = True,
) -> list[str]:
    """Return stable, deduplicated canonical reasoning modes.

    Unknown values are preserved so authorization can fail closed rather than
    silently dropping an unrecognized requested capability.
    """

    normalized: list[str] = []
    seen: set[str] = set()

    for raw in values:
        value = str(getattr(raw, "value", raw)).strip().lower()
        if not value:
            continue

        expanded = _LEGACY_ALIASES.get(value) if allow_legacy else None
        candidates = expanded or (value,)
        for candidate in candidates:
            if candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)

    return normalized


def is_legacy_reasoning_mode(value: str) -> bool:
    return str(value).strip().lower() in _LEGACY_ALIASES


__all__ = [
    "CANONICAL_REASONING_MODES",
    "is_legacy_reasoning_mode",
    "normalize_reasoning_modes",
]
