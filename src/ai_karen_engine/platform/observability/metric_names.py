from __future__ import annotations

"""Canonical metric names and bounded label vocabulary for platform metrics.

Centralize metric names so dashboards, alerts, and adapters agree on one
vocabulary. Labels are intentionally bounded: high-cardinality identifiers
belong in structured events, never as metric labels (OBS-106).
"""

from typing import Final

NAMESPACE: Final = "kari"

# Request lifecycle
REQUESTS_TOTAL: Final = f"{NAMESPACE}_requests_total"
REQUEST_LATENCY_MS: Final = f"{NAMESPACE}_request_latency_ms"

# Provider
PROVIDER_REQUESTS_TOTAL: Final = f"{NAMESPACE}_provider_requests_total"
PROVIDER_FAILURES_TOTAL: Final = f"{NAMESPACE}_provider_failures_total"
PROVIDER_FALLBACKS_TOTAL: Final = f"{NAMESPACE}_provider_fallbacks_total"
PROVIDER_LATENCY_MS: Final = f"{NAMESPACE}_provider_latency_ms"

# Memory
MEMORY_RECALL_LATENCY_MS: Final = f"{NAMESPACE}_memory_recall_latency_ms"
MEMORY_RECALL_COUNT: Final = f"{NAMESPACE}_memory_recall_count"

# Prompt
PROMPT_TOKENS_ESTIMATED: Final = f"{NAMESPACE}_prompt_tokens_estimated"

# Extensions / plugins
EXTENSION_EXECUTIONS_TOTAL: Final = f"{NAMESPACE}_extension_executions_total"
EXTENSION_FAILURES_TOTAL: Final = f"{NAMESPACE}_extension_failures_total"

# Persistence
PERSISTENCE_FAILURES_TOTAL: Final = f"{NAMESPACE}_persistence_failures_total"

# Diagnostics
DEGRADED_REQUESTS_TOTAL: Final = f"{NAMESPACE}_degraded_requests_total"

# Bounded label vocabulary. Keys are allowed label names; values are the
# documented legal value sets where enumeration is feasible.
BOUNDED_LABELS: Final = {
    "provider": (),
    "model_family": (),
    "runtime_engine": (),
    "execution_layer": (),
    "status": ("success", "failure", "denied", "started", "completed", "failed", "degraded"),
    "error_code": ("rate_limit", "timeout", "unavailable", "policy_denied", "validation"),
    "capability": (),
    "plugin_id": (),
    "event_type": (),
    "fallback_level": (),
    "response_source": (),
    "tool": (),
}
