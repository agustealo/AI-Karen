"""
Metrics and Observability for Case-Memory Learning System
Provides monitoring hooks and metrics collection for case-memory operations
"""

import logging
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

@dataclass
class CaseMemoryMetrics:
    """Metrics data structure for case-memory operations"""
    
    # Admission metrics
    cases_admitted_total: int = 0
    cases_rejected_total: int = 0
    admission_latency_seconds: float = 0.0
    
    # Retrieval metrics
    retrievals_total: int = 0
    retrieval_latency_seconds: float = 0.0
    hints_provided_total: int = 0
    avg_similarity_score: float = 0.0
    
    # Storage metrics
    postgres_operations_total: int = 0
    redis_operations_total: int = 0
    
    # Error metrics
    admission_errors_total: int = 0
    retrieval_errors_total: int = 0
    storage_errors_total: int = 0
    
    # Performance metrics
    avg_case_size_bytes: float = 0.0
    memory_usage_bytes: int = 0
    
    # Business metrics
    reward_distribution: Dict[str, int] = None
    category_distribution: Dict[str, int] = None
    
    def __post_init__(self):
        if self.reward_distribution is None:
            self.reward_distribution = defaultdict(int)
        if self.category_distribution is None:
            self.category_distribution = defaultdict(int)

class CaseMemoryObserver:
    """
    Observability system for case-memory learning
    
    Features:
    - Real-time metrics collection
    - Performance monitoring
    - Error tracking
    - Business intelligence
    - Alerting hooks
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        self.metrics_window_size = self.config.get('metrics_window_size', 1000)
        self.alert_thresholds = self.config.get('alert_thresholds', {})
        
        # Metrics storage
        self.metrics = CaseMemoryMetrics()
        self.recent_operations = deque(maxlen=self.metrics_window_size)
        self.performance_history = deque(maxlen=100)  # Last 100 operations
        
        # Timing contexts
        self._timing_contexts = {}
        
        # Alert callbacks
        self.alert_callbacks = []
        
    def start_timing(self, operation_id: str, operation_type: str) -> None:
        """Start timing an operation"""
        if not self.enabled:
            return
            
        self._timing_contexts[operation_id] = {
            'start_time': time.time(),
            'operation_type': operation_type
        }
    
    def end_timing(self, operation_id: str, success: bool = True, **metadata) -> float:
        """End timing an operation and record metrics"""
        if not self.enabled or operation_id not in self._timing_contexts:
            return 0.0
        
        context = self._timing_contexts.pop(operation_id)
        duration = time.time() - context['start_time']
        
        # Record operation
        operation_record = {
            'timestamp': datetime.now(),
            'operation_type': context['operation_type'],
            'duration': duration,
            'success': success,
            'metadata': metadata
        }
        self.recent_operations.append(operation_record)
        self.performance_history.append(duration)
        
        # Update metrics based on operation type
        if context['operation_type'] == 'admission':
            if success:
                self.metrics.cases_admitted_total += 1
                self.metrics.admission_latency_seconds = self._update_avg(
                    self.metrics.admission_latency_seconds, duration, self.metrics.cases_admitted_total
                )
            else:
                self.metrics.cases_rejected_total += 1
                self.metrics.admission_errors_total += 1
                
        elif context['operation_type'] == 'retrieval':
            if success:
                self.metrics.retrievals_total += 1
                self.metrics.retrieval_latency_seconds = self._update_avg(
                    self.metrics.retrieval_latency_seconds, duration, self.metrics.retrievals_total
                )
                
                # Update similarity score if provided
                if 'avg_score' in metadata:
                    self.metrics.avg_similarity_score = self._update_avg(
                        self.metrics.avg_similarity_score, metadata['avg_score'], self.metrics.retrievals_total
                    )
                
                # Update hints provided
                if 'hints_count' in metadata:
                    self.metrics.hints_provided_total += metadata['hints_count']
            else:
                self.metrics.retrieval_errors_total += 1
        
        # Check for alerts
        self._check_alerts(operation_record)
        
        return duration
    
    def record_case_admission(
        self, 
        case_size_bytes: int, 
        reward: float, 
        category: Optional[str] = None
    ) -> None:
        """Record case admission metrics"""
        if not self.enabled:
            return
        
        # Update size metrics
        total_cases = self.metrics.cases_admitted_total
        if total_cases > 0:
            self.metrics.avg_case_size_bytes = self._update_avg(
                self.metrics.avg_case_size_bytes, case_size_bytes, total_cases
            )
        else:
            self.metrics.avg_case_size_bytes = case_size_bytes
        
        # Update reward distribution
        reward_bucket = self._get_reward_bucket(reward)
        self.metrics.reward_distribution[reward_bucket] += 1
        
        # Update category distribution
        if category:
            self.metrics.category_distribution[category] += 1
    
    def record_storage_operation(self, storage_type: str, success: bool = True) -> None:
        """Record storage operation metrics"""
        if not self.enabled:
            return
        
        if storage_type == 'postgres':
            self.metrics.postgres_operations_total += 1
        elif storage_type == 'redis':
            self.metrics.redis_operations_total += 1
        
        if not success:
            self.metrics.storage_errors_total += 1
    
    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """Get current metrics snapshot"""
        if not self.enabled:
            return {}
        
        # Calculate derived metrics
        total_operations = len(self.recent_operations)
        error_rate = 0.0
        if total_operations > 0:
            errors = sum(1 for op in self.recent_operations if not op['success'])
            error_rate = errors / total_operations
        
        avg_latency = 0.0
        if self.performance_history:
            avg_latency = sum(self.performance_history) / len(self.performance_history)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'admission': {
                'cases_admitted': self.metrics.cases_admitted_total,
                'cases_rejected': self.metrics.cases_rejected_total,
                'avg_latency_seconds': self.metrics.admission_latency_seconds,
                'errors': self.metrics.admission_errors_total
            },
            'retrieval': {
                'retrievals_total': self.metrics.retrievals_total,
                'hints_provided': self.metrics.hints_provided_total,
                'avg_latency_seconds': self.metrics.retrieval_latency_seconds,
                'avg_similarity_score': self.metrics.avg_similarity_score,
                'errors': self.metrics.retrieval_errors_total
            },
            'storage': {
                'postgres_operations': self.metrics.postgres_operations_total,
                'redis_operations': self.metrics.redis_operations_total,
                'errors': self.metrics.storage_errors_total
            },
            'performance': {
                'avg_case_size_bytes': self.metrics.avg_case_size_bytes,
                'memory_usage_bytes': self.metrics.memory_usage_bytes,
                'error_rate': error_rate,
                'avg_operation_latency': avg_latency,
                'recent_operations_count': total_operations
            },
            'distributions': {
                'reward_buckets': dict(self.metrics.reward_distribution),
                'categories': dict(self.metrics.category_distribution)
            }
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get system health status"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        # Calculate health indicators
        recent_ops = list(self.recent_operations)[-50:]  # Last 50 operations
        if not recent_ops:
            return {'status': 'no_data'}
        
        # Error rate
        error_count = sum(1 for op in recent_ops if not op['success'])
        error_rate = error_count / len(recent_ops)
        
        # Average latency
        avg_latency = sum(op['duration'] for op in recent_ops) / len(recent_ops)
        
        # Determine status
        status = 'healthy'
        issues = []
        
        if error_rate > self.alert_thresholds.get('error_rate', 0.1):
            status = 'degraded'
            issues.append(f'High error rate: {error_rate:.2%}')
        
        if avg_latency > self.alert_thresholds.get('latency_threshold', 5.0):
            status = 'degraded'
            issues.append(f'High latency: {avg_latency:.2f}s')
        
        if error_rate > self.alert_thresholds.get('critical_error_rate', 0.5):
            status = 'critical'
        
        return {
            'status': status,
            'error_rate': error_rate,
            'avg_latency': avg_latency,
            'recent_operations': len(recent_ops),
            'issues': issues,
            'last_updated': datetime.now().isoformat()
        }
    
    def add_alert_callback(self, callback) -> None:
        """Add alert callback function"""
        self.alert_callbacks.append(callback)
    
    def _update_avg(self, current_avg: float, new_value: float, count: int) -> float:
        """Update running average"""
        if count <= 1:
            return new_value
        return ((current_avg * (count - 1)) + new_value) / count
    
    def _get_reward_bucket(self, reward: float) -> str:
        """Get reward bucket for distribution tracking"""
        if reward < 0:
            return 'negative'
        elif reward == 0:
            return 'zero'
        elif reward < 0.5:
            return 'low'
        elif reward < 0.8:
            return 'medium'
        else:
            return 'high'
    
    def _check_alerts(self, operation_record: Dict[str, Any]) -> None:
        """Check for alert conditions and trigger callbacks"""
        if not self.alert_callbacks:
            return
        
        # Check error rate threshold
        recent_ops = list(self.recent_operations)[-10:]  # Last 10 operations
        if len(recent_ops) >= 10:
            error_count = sum(1 for op in recent_ops if not op['success'])
            error_rate = error_count / len(recent_ops)
            
            if error_rate > self.alert_thresholds.get('error_rate', 0.1):
                alert = {
                    'type': 'high_error_rate',
                    'severity': 'warning',
                    'message': f'Case-memory error rate {error_rate:.2%} exceeds threshold',
                    'timestamp': datetime.now().isoformat(),
                    'metadata': {'error_rate': error_rate, 'recent_operations': len(recent_ops)}
                }
                self._trigger_alerts(alert)
        
        # Check latency threshold
        if operation_record['duration'] > self.alert_thresholds.get('latency_threshold', 5.0):
            alert = {
                'type': 'high_latency',
                'severity': 'warning',
                'message': f'Case-memory operation took {operation_record["duration"]:.2f}s',
                'timestamp': datetime.now().isoformat(),
                'metadata': operation_record
            }
            self._trigger_alerts(alert)
    
    def _trigger_alerts(self, alert: Dict[str, Any]) -> None:
        """Trigger alert callbacks"""
        for callback in self.alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(alert))
                else:
                    callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

# Global observer instance
_global_observer: Optional[CaseMemoryObserver] = None

def get_observer() -> CaseMemoryObserver:
    """Get global case-memory observer instance"""
    global _global_observer
    if _global_observer is None:
        _global_observer = CaseMemoryObserver()
    return _global_observer

def initialize_observer(config: Optional[Dict[str, Any]] = None) -> CaseMemoryObserver:
    """Initialize global observer with configuration"""
    global _global_observer
    _global_observer = CaseMemoryObserver(config)
    return _global_observer
