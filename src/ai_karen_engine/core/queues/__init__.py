"""Queue package marker.

Platform-agnostic durable queue contracts.
"""

from ai_karen_engine.core.queues.catalog import QUEUE_CATALOG, QueueDefinition, get_queue_definition
from ai_karen_engine.core.queues.contracts import (
    DeliveryStatus,
    DurableQueue,
    QueueDelivery,
    QueueMessage,
    QueueType,
)
from ai_karen_engine.core.queues.fake import FakeDurableQueue
from ai_karen_engine.core.queues.retry import (
    ErrorClass,
    RetryPolicy,
    RetryResult,
    classify_error,
    compute_retry,
)

__all__ = [
    "QUEUE_CATALOG",
    "QueueDefinition",
    "get_queue_definition",
    "DeliveryStatus",
    "DurableQueue",
    "QueueDelivery",
    "QueueMessage",
    "QueueType",
    "FakeDurableQueue",
    "ErrorClass",
    "RetryPolicy",
    "RetryResult",
    "classify_error",
    "compute_retry",
]
