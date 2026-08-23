"""
Memory Metrics for AI Karen Memory System.

Provides specialized Prometheus metrics for memory operations, 
including extraction, scoring, admission, projection, and EchoCore health.
"""

import logging
from typing import Dict, Any
from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)

def register_memory_metrics() -> Dict[str, Any]:
    """Register all memory-related metrics safely."""
    manager = get_metrics_manager()
    metrics = {}
    
    with manager.safe_metrics_context():
        # 1. Online Pipeline Metrics
        metrics['extraction_count'] = manager.register_counter(
            'karen_memory_extraction_total',
            'Total interactions processed for memory extraction',
            ['tenant_id', 'status']
        )
        
        metrics['signals_extracted'] = manager.register_counter(
            'karen_memory_signals_extracted_total',
            'Total raw signals extracted from interactions',
            ['signal_type']
        )
        
        metrics['admission_count'] = manager.register_counter(
            'karen_memory_admissions_total',
            'Total signals admitted to durable memory',
            ['signal_type']
        )
        
        metrics['extraction_latency'] = manager.register_histogram(
            'karen_memory_extraction_latency_ms',
            'Latency of memory extraction pipeline in ms',
            ['stage'] # e.g., 'spacy', 'distilbert', 'total'
        )

        # 2. Projection Metrics
        metrics['projection_lag'] = manager.register_histogram(
            'karen_memory_projection_lag_seconds',
            'Latency between ledger write and projection completion',
            ['store'] # e.g., 'milvus', 'elastic', 'redis'
        )
        
        metrics['projection_failures'] = manager.register_counter(
            'karen_memory_projection_failures_total',
            'Total failed memory projections',
            ['store', 'error_type']
        )

        # 3. EchoCore Metrics
        metrics['echocore_backlog'] = manager.register_gauge(
            'karen_memory_echocore_backlog_events',
            'Number of memory events waiting for offline consolidation',
            ['tenant_id']
        )
        
        metrics['contradiction_count'] = manager.register_gauge(
            'karen_memory_open_contradictions_total',
            'Total unresolved contradictions in the ledger',
            ['tenant_id']
        )
        
        # 4. Resilience Metrics
        metrics['circuit_breaker_state'] = manager.register_gauge(
            'karen_memory_circuit_breaker_state',
            'State of memory circuit breakers (0=CLOSED, 1=OPEN, 2=HALF_OPEN)',
            ['stage']
        )
        
        metrics['fallback_usage'] = manager.register_counter(
            'karen_memory_fallback_triggers_total',
            'Total times a memory stage triggered a fallback',
            ['stage']
        )

    return metrics

# Singleton instance
_memory_metrics = None

def get_memory_metrics() -> Dict[str, Any]:
    global _memory_metrics
    if _memory_metrics is None:
        _memory_metrics = register_memory_metrics()
    return _memory_metrics
