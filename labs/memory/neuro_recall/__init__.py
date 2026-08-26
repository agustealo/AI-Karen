"""NeuroRecall labs harness guardrail.

This package is intentionally blocked in production runtime paths unless
`KARI_NEURO_RECALL_LABS_ENABLED=true`.
"""

from __future__ import annotations

import os


def _labs_enabled() -> bool:
    return os.getenv("KARI_NEURO_RECALL_LABS_ENABLED", "false").lower() in {"1", "true", "yes"}


if not _labs_enabled():
    raise RuntimeError(
        "NeuroRecall is labs-only and disabled by default. "
        "Set KARI_NEURO_RECALL_LABS_ENABLED=true for research/evaluation usage."
    )


__all__ = ["_labs_enabled"]
