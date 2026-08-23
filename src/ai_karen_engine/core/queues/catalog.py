"""Queue catalog.

Centralized queue names with type-safe classification.
No arbitrary strings throughout services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai_karen_engine.core.queues.contracts import QueueType


@dataclass(frozen=True)
class QueueDefinition:
    name: str
    queue_type: QueueType
    retry_policy: str = "exponential"
    visibility_timeout_seconds: int = 300
    owner: str = "platform"
    schema_version: str = "v1"


QUEUE_CATALOG: Dict[str, QueueDefinition] = {
    QueueType.MEMORY_CONSOLIDATION.value: QueueDefinition(
        name=QueueType.MEMORY_CONSOLIDATION.value,
        queue_type=QueueType.MEMORY_CONSOLIDATION,
        owner="memory",
    ),
    QueueType.MEMORY_EMBEDDING.value: QueueDefinition(
        name=QueueType.MEMORY_EMBEDDING.value,
        queue_type=QueueType.MEMORY_EMBEDDING,
        owner="memory",
    ),
    QueueType.MEMORY_REEMBEDDING.value: QueueDefinition(
        name=QueueType.MEMORY_REEMBEDDING.value,
        queue_type=QueueType.MEMORY_REEMBEDDING,
        owner="memory",
    ),
    QueueType.ARTIFACT_RECONCILE.value: QueueDefinition(
        name=QueueType.ARTIFACT_RECONCILE.value,
        queue_type=QueueType.ARTIFACT_RECONCILE,
        owner="storage",
    ),
    QueueType.ARTIFACT_CLEANUP.value: QueueDefinition(
        name=QueueType.ARTIFACT_CLEANUP.value,
        queue_type=QueueType.ARTIFACT_CLEANUP,
        owner="storage",
    ),
    QueueType.RUNTIME_POST_EXECUTION.value: QueueDefinition(
        name=QueueType.RUNTIME_POST_EXECUTION.value,
        queue_type=QueueType.RUNTIME_POST_EXECUTION,
        owner="runtime",
    ),
    QueueType.NOTIFICATION_DELIVERY.value: QueueDefinition(
        name=QueueType.NOTIFICATION_DELIVERY.value,
        queue_type=QueueType.NOTIFICATION_DELIVERY,
        owner="notifications",
    ),
    QueueType.ANALYTICS_ROLLUP.value: QueueDefinition(
        name=QueueType.ANALYTICS_ROLLUP.value,
        queue_type=QueueType.ANALYTICS_ROLLUP,
        owner="analytics",
    ),
}


def get_queue_definition(queue_name: str) -> QueueDefinition:
    if queue_name not in QUEUE_CATALOG:
        raise ValueError(f"Unknown queue: {queue_name!r}. Known queues: {sorted(QUEUE_CATALOG)}")
    return QUEUE_CATALOG[queue_name]
