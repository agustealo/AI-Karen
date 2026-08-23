"""Queue contract tests."""

from __future__ import annotations

import uuid
import asyncio
import pytest

from ai_karen_engine.core.queues.contracts import QueueMessage, QueueType, DeliveryStatus
from ai_karen_engine.core.queues.catalog import QUEUE_CATALOG, get_queue_definition
from ai_karen_engine.core.queues.retry import classify_error, compute_retry, RetryPolicy, ErrorClass
from ai_karen_engine.core.queues.fake import FakeDurableQueue


def test_queue_catalog_complete():
    assert len(QUEUE_CATALOG) == 8
    assert QueueType.MEMORY_CONSOLIDATION.value in QUEUE_CATALOG


def test_get_queue_definition_unknown():
    with pytest.raises(ValueError):
        get_queue_definition("unknown.queue")


def test_classify_error_permanent():
    exc = Exception("invalid payload")
    assert classify_error(exc) == ErrorClass.INVALID_PAYLOAD


def test_compute_retry_exceeds_max():
    policy = RetryPolicy(max_attempts=2)
    result = compute_retry(policy, 2, ErrorClass.RETRYABLE)
    assert result.should_retry is False
    assert result.dead_letter is True


@pytest.mark.asyncio
async def test_fake_queue_enqueue_and_receive():
    queue = FakeDurableQueue()
    message = QueueMessage(queue=QueueType.MEMORY_CONSOLIDATION.value, type="test")
    await queue.enqueue(message)
    deliveries = await queue.receive(QueueType.MEMORY_CONSOLIDATION.value)
    assert len(deliveries) == 1
    assert deliveries[0].status == DeliveryStatus.IN_PROGRESS
