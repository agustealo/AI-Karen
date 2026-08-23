"""
Validation System Metrics for Prometheus Monitoring

This module provides comprehensive metrics collection for the HTTP request validation system,
including validation events, security threats, rate limiting, and performance monitoring.
"""

import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)


class ValidationEventType(Enum):
    """Types of validation events"""
    REQUEST_VALIDATED = "request_validated"
    REQUEST_REJECTED = "request_rejected"
    SECURITY_THREAT_DETECTED = "security_threat_detected"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    VALIDATION_ERROR = "validation_error"


class ThreatLevel(Enum):
    """Security threat levels"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ValidationMetricsData:
    """Data structure for validation metrics"""
    event_type: ValidationEventType
    threat_level: ThreatLevel = ThreatLevel.NONE
    validation_rule: str = "unknown"
    client_ip_hash: str = "unknown"
    endpoint: str = "unknown"
    http_method: str = "unknown"
    user_agent_category: str = "unknown"
    processing_time_ms: float = 0.0
    attack_categories: List[str] = None
    rate_limit_rule: str = "unknown"
    additional_labels: Dict[str, str] = None

    def __post_init__(self):
        if self.attack_categories is None:
            self.attack_categories = []
        if self.additional_labels is None:
            self.additional_labels = {}


class ValidationMetricsCollector:
    """
    Collects and exposes Prometheus metrics for the HTTP validation system
    """
    
    def __init__(self):
        self.metrics_manager = get_metrics_manager()
        self._initialize_metrics()
        self._start_time = time.time()
        
        # Cache for performance optimization
        self._metric_cache = {}
        self._cache_ttl = 60  # 1 minute
        self._last_cache_clear = time.time()
    
    def _initialize_metrics(self):
        """Initialize all Prometheus metrics for validation system"""
        
        # Core validation metrics
        self.validation_requests_total = self.metrics_manager.register_counter(
            'http_validation_requests_total',
            'Total HTTP validation requests processed',
            ['event_type', 'validation_rule', 'endpoint', 'method', 'result']
        )
        
        self.validation_duration_seconds = self.metrics_manager.register_histogram(
            'http_validation_duration_seconds',
            'Time spent on HTTP request validation',
            ['validation_rule', 'endpoint', 'method'],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        )
        
        # Security threat metrics
        self.security_threats_total = self.metrics_manager.register_counter(
            'http_security_threats_total',
            'Total security threats detected',
            ['threat_level', 'attack_category', 'endpoint', 'method', 'client_reputation']
        )
        
        self.security_threat_confidence = self.metrics_manager.register_histogram(
            'http_security_threat_confidence',
            'Confidence score of security threat detection',
            ['threat_level', 'attack_category'],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        self.blocked_requests_total = self.metrics_manager.register_counter(
            'http_blocked_requests_total',
            'Total blocked requests by reason',
            ['block_reason', 'threat_level', 'endpoint', 'method']
        )
        
        # Rate limiting metrics
        self.rate_limit_events_total = self.metrics_manager.register_counter(
            'http_rate_limit_events_total',
            'Total rate limiting events',
            ['rule_name', 'scope', 'algorithm', 'action', 'endpoint']
        )
        
        self.rate_limit_current_usage = self.metrics_manager.register_gauge(
            'http_rate_limit_current_usage',
            'Current rate limit usage as percentage of limit',
            ['rule_name', 'scope', 'client_hash', 'endpoint']
        )
        
        self.rate_limit_reset_time = self.metrics_manager.register_gauge(
            'http_rate_limit_reset_time_seconds',
            'Time until rate limit resets (Unix timestamp)',
            ['rule_name', 'scope', 'client_hash', 'endpoint']
        )
        
        # Attack pattern metrics
        self.attack_patterns_detected = self.metrics_manager.register_counter(
            'http_attack_patterns_detected_total',
            'Total attack patterns detected by type',
            ['pattern_type', 'pattern_category', 'endpoint', 'method']
        )
        
        self.attack_pattern_frequency = self.metrics_manager.register_histogram(
            'http_attack_pattern_frequency',
            'Frequency of attack patterns per request',
            ['pattern_category'],
            buckets=[1, 2, 3, 5, 10, 20, 50, 100]
        )
        
        # Client behavior metrics
        self.client_reputation_score = self.metrics_manager.register_histogram(
            'http_client_reputation_score',
            'Client reputation scores',
            ['reputation_category', 'endpoint'],
            buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        self.suspicious_clients_total = self.metrics_manager.register_counter(
            'http_suspicious_clients_total',
            'Total suspicious client activities',
            ['activity_type', 'reputation', 'endpoint']
        )
        
        # Performance and health metrics
        self.validation_errors_total = self.metrics_manager.register_counter(
            'http_validation_errors_total',
            'Total validation system errors',
            ['error_type', 'component', 'severity']
        )
        
        self.validation_system_health = self.metrics_manager.register_gauge(
            'http_validation_system_health',
            'Validation system health status (1=healthy, 0=unhealthy)',
            ['component']
        )
        
        self.threat_intelligence_entries = self.metrics_manager.register_gauge(
            'http_threat_intelligence_entries_total',
            'Total entries in threat intelligence database',
            ['entry_type']
        )
        
        # Request characteristics metrics
        self.request_size_bytes = self.metrics_manager.register_histogram(
            'http_request_size_bytes',
            'HTTP request size distribution',
            ['endpoint', 'method', 'validation_result'],
            buckets=[100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000]
        )
        
        self.request_headers_count = self.metrics_manager.register_histogram(
            'http_request_headers_count',
            'Number of headers per request',
            ['endpoint', 'method', 'validation_result'],
            buckets=[1, 5, 10, 15, 20, 30, 50, 100]
        )
        
        # User agent analysis metrics
        self.user_agent_categories = self.metrics_manager.register_counter(
            'http_user_agent_categories_total',
            'User agent categories detected',
            ['category', 'validation_result', 'endpoint']
        )
        
        # Geographic and temporal metrics
        self.validation_events_by_hour = self.metrics_manager.register_counter(
            'http_validation_events_by_hour_total',
            'Validation events by hour of day',
            ['hour', 'event_type', 'threat_level']
        )
        
        logger.info("Validation metrics initialized successfully")
    
    def record_validation_event(self, metrics_data: ValidationMetricsData):
        """
        Record a validation event with comprehensive metrics
        
        Args:
            metrics_data: ValidationMetricsData containing event details
        """
        try:
            # Core validation metrics
            self.validation_requests_total.labels(
                event_type=metrics_data.event_type.value,
                validation_rule=metrics_data.validation_rule,
                endpoint=self._sanitize_endpoint(metrics_data.endpoint),
                method=metrics_data.http_method,
                result="allowed" if metrics_data.event_type == ValidationEventType.REQUEST_VALIDATED else "blocked"
            ).inc()
            
            # Record processing time
            if metrics_data.processing_time_ms > 0:
                self.validation_duration_seconds.labels(
                    validation_rule=metrics_data.validation_rule,
                    endpoint=self._sanitize_endpoint(metrics_data.endpoint),
                    method=metrics_data.http_method
                ).observe(metrics_data.processing_time_ms / 1000.0)
            
            # Security threat metrics
            if metrics_data.threat_level != ThreatLevel.NONE:
                self._record_security_metrics(metrics_data)
            
            # Rate limiting metrics
            if metrics_data.event_type == ValidationEventType.RATE_LIMIT_EXCEEDED:
                self._record_rate_limit_metrics(metrics_data)
            
            # Attack pattern metrics
            if metrics_data.attack_categories:
                self._record_attack_pattern_metrics(metrics_data)
            
            # User agent metrics
            if metrics_data.user_agent_category != "unknown":
                self.user_agent_categories.labels(
                    category=metrics_data.user_agent_category,
                    validation_result="allowed" if metrics_data.event_type == ValidationEventType.REQUEST_VALIDATED else "blocked",
                    endpoint=self._sanitize_endpoint(metrics_data.endpoint)
                ).inc()
            
            # Temporal metrics
            current_hour = datetime.now().hour
            self.validation_events_by_hour.labels(
                hour=str(current_hour),
                event_type=metrics_data.event_type.value,
                threat_level=metrics_data.threat_level.value
            ).inc()
            
            # Clear cache periodically
            self._maybe_clear_cache()
            
        except Exception as e:
            logger.error(f"Error recording validation metrics: {e}", exc_info=True)
            self._record_error_metric("metric_recording_error", "metrics_collector", "error")
    
    def _record_security_metrics(self, metrics_data: ValidationMetricsData):
        """Record security-specific metrics"""
        try:
            # Main security threat counter
            for attack_category in metrics_data.attack_categories or ["unknown"]:
                self.security_threats_total.labels(
                    threat_level=metrics_data.threat_level.value,
                    attack_category=attack_category,
                    endpoint=self._sanitize_endpoint(metrics_data.endpoint),
                    method=metrics_data.http_method,
                    client_reputation=metrics_data.additional_labels.get("client_reputation", "unknown")
                ).inc()
            
            # Record blocked requests
            if metrics_data.event_type == ValidationEventType.REQUEST_REJECTED:
                self.blocked_requests_total.labels(
                    block_reason="security_threat",
                    threat_level=metrics_data.threat_level.value,
                    endpoint=self._sanitize_endpoint(metrics_data.endpoint),
                    method=metrics_data.http_method
                ).inc()
            
            # Record confidence score if available
            confidence_score = metrics_data.additional_labels.get("confidence_score")
            if confidence_score:
                try:
                    confidence_float = float(confidence_score)
                    for attack_category in metrics_data.attack_categories or ["unknown"]:
                        self.security_threat_confidence.labels(
                            threat_level=metrics_data.threat_level.value,
                            attack_category=attack_category
                        ).observe(confidence_float)
                except (ValueError, TypeError):
                    pass
            
        except Exception as e:
            logger.error(f"Error recording security metrics: {e}")
    
    def _record_rate_limit_metrics(self, metrics_data: ValidationMetricsData):
        """Record rate limiting specific metrics"""
        try:
            self.rate_limit_events_total.labels(
                rule_name=metrics_data.rate_limit_rule,
                scope=metrics_data.additional_labels.get("rate_limit_scope", "unknown"),
                algorithm=metrics_data.additional_labels.get("rate_limit_algorithm", "unknown"),
                action="blocked",
                endpoint=self._sanitize_endpoint(metrics_data.endpoint)
            ).inc()
            
            # Record current usage if available
            current_usage = metrics_data.additional_labels.get("current_usage_percent")
            if current_usage:
                try:
                    usage_float = float(current_usage)
                    self.rate_limit_current_usage.labels(
                        rule_name=metrics_data.rate_limit_rule,
                        scope=metrics_data.additional_labels.get("rate_limit_scope", "unknown"),
                        client_hash=metrics_data.client_ip_hash,
                        endpoint=self._sanitize_endpoint(metrics_data.endpoint)
                    ).set(usage_float)
                except (ValueError, TypeError):
                    pass
            
            # Record reset time if available
            reset_time = metrics_data.additional_labels.get("reset_time_unix")
            if reset_time:
                try:
                    reset_float = float(reset_time)
                    self.rate_limit_reset_time.labels(
                        rule_name=metrics_data.rate_limit_rule,
                        scope=metrics_data.additional_labels.get("rate_limit_scope", "unknown"),
                        client_hash=metrics_data.client_ip_hash,
                        endpoint=self._sanitize_endpoint(metrics_data.endpoint)
                    ).set(reset_float)
                except (ValueError, TypeError):
                    pass
                    
        except Exception as e:
            logger.error(f"Error recording rate limit metrics: {e}")
    
    def _record_attack_pattern_metrics(self, metrics_data: ValidationMetricsData):
        """Record attack pattern specific metrics"""
        try:
            for attack_category in metrics_data.attack_categories:
                self.attack_patterns_detected.labels(
                    pattern_type=attack_category,
                    pattern_category=self._categorize_attack_type(attack_category),
                    endpoint=self._sanitize_endpoint(metrics_data.endpoint),
                    method=metrics_data.http_method
                ).inc()
            
            # Record frequency of patterns
            pattern_count = len(metrics_data.attack_categories)
            if pattern_count > 0:
                primary_category = self._get_primary_attack_category(metrics_data.attack_categories)
                self.attack_pattern_frequency.labels(
                    pattern_category=primary_category
                ).observe(pattern_count)
                
        except Exception as e:
            logger.error(f"Error recording attack pattern metrics: {e}")
    
    def record_client_behavior(
        self,
        client_ip_hash: str,
        reputation_score: float,
        reputation_category: str,
        endpoint: str,
        activity_type: str = "normal"
    ):
        """
        Record client behavior metrics
        
        Args:
            client_ip_hash: Hashed client IP
            reputation_score: Reputation score (0.0 to 1.0)
            reputation_category: Category of reputation
            endpoint: Request endpoint
            activity_type: Type of activity observed
        """
        try:
            self.client_reputation_score.labels(
                reputation_category=reputation_category,
                endpoint=self._sanitize_endpoint(endpoint)
            ).observe(reputation_score)
            
            if activity_type != "normal":
                self.suspicious_clients_total.labels(
                    activity_type=activity_type,
                    reputation=reputation_category,
                    endpoint=self._sanitize_endpoint(endpoint)
                ).inc()
                
        except Exception as e:
            logger.error(f"Error recording client behavior metrics: {e}")
    
    def record_request_characteristics(
        self,
        endpoint: str,
        method: str,
        size_bytes: int,
        headers_count: int,
        validation_result: str
    ):
        """
        Record request characteristics metrics
        
        Args:
            endpoint: Request endpoint
            method: HTTP method
            size_bytes: Request size in bytes
            headers_count: Number of headers
            validation_result: Validation result (allowed/blocked)
        """
        try:
            self.request_size_bytes.labels(
                endpoint=self._sanitize_endpoint(endpoint),
                method=method,
                validation_result=validation_result
            ).observe(size_bytes)
            
            self.request_headers_count.labels(
                endpoint=self._sanitize_endpoint(endpoint),
                method=method,
                validation_result=validation_result
            ).observe(headers_count)
            
        except Exception as e:
            logger.error(f"Error recording request characteristics: {e}")
    
    def update_system_health(self, component: str, is_healthy: bool):
        """
        Update system health metrics
        
        Args:
            component: Component name
            is_healthy: Whether component is healthy
        """
        try:
            self.validation_system_health.labels(component=component).set(1 if is_healthy else 0)
        except Exception as e:
            logger.error(f"Error updating system health: {e}")
    
    def update_threat_intelligence_stats(self, stats: Dict[str, int]):
        """
        Update threat intelligence statistics
        
        Args:
            stats: Dictionary with threat intelligence statistics
        """
        try:
            for entry_type, count in stats.items():
                self.threat_intelligence_entries.labels(entry_type=entry_type).set(count)
        except Exception as e:
            logger.error(f"Error updating threat intelligence stats: {e}")
    
    def _record_error_metric(self, error_type: str, component: str, severity: str):
        """Record validation system errors"""
        try:
            self.validation_errors_total.labels(
                error_type=error_type,
                component=component,
                severity=severity
            ).inc()
        except Exception as e:
            logger.error(f"Error recording error metric: {e}")
    
    def _sanitize_endpoint(self, endpoint: str) -> str:
        """Sanitize endpoint for metrics to prevent cardinality explosion"""
        if not endpoint or endpoint == "unknown":
            return "unknown"
        
        # Cache sanitized endpoints
        if endpoint in self._metric_cache:
            return self._metric_cache[endpoint]
        
        # Remove query parameters and fragments
        sanitized = endpoint.split('?')[0].split('#')[0]
        
        # Replace dynamic segments with placeholders
        import re
        
        # Replace UUIDs
        sanitized = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{uuid}', sanitized, flags=re.IGNORECASE)
        
        # Replace numeric IDs
        sanitized = re.sub(r'/\d+', '/{id}', sanitized)
        
        # Replace long alphanumeric strings (likely IDs)
        sanitized = re.sub(r'/[a-zA-Z0-9]{16,}', '/{token}', sanitized)
        
        # Limit length
        if len(sanitized) > 100:
            sanitized = sanitized[:97] + "..."
        
        # Cache the result
        self._metric_cache[endpoint] = sanitized
        return sanitized
    
    def _categorize_attack_type(self, attack_type: str) -> str:
        """Categorize attack types into broader categories"""
        injection_types = ["sql_injection", "nosql_injection", "ldap_injection", "command_injection"]
        script_types = ["xss", "csrf"]
        traversal_types = ["path_traversal"]
        header_types = ["header_injection"]
        
        if attack_type in injection_types:
            return "injection"
        elif attack_type in script_types:
            return "script"
        elif attack_type in traversal_types:
            return "traversal"
        elif attack_type in header_types:
            return "header"
        else:
            return "other"
    
    def _get_primary_attack_category(self, attack_categories: List[str]) -> str:
        """Get the primary attack category from a list"""
        if not attack_categories:
            return "unknown"
        
        # Priority order for attack categories
        priority_order = [
            "sql_injection", "command_injection", "nosql_injection",
            "xss", "csrf", "path_traversal", "header_injection",
            "ldap_injection", "xml_injection"
        ]
        
        for priority_attack in priority_order:
            if priority_attack in attack_categories:
                return priority_attack
        
        return attack_categories[0]
    
    def _maybe_clear_cache(self):
        """Clear metric cache periodically to prevent memory leaks"""
        current_time = time.time()
        if current_time - self._last_cache_clear > self._cache_ttl:
            self._metric_cache.clear()
            self._last_cache_clear = current_time
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of collected metrics"""
        try:
            uptime_seconds = time.time() - self._start_time
            
            return {
                "collector_uptime_seconds": uptime_seconds,
                "metrics_registered": len(self.metrics_manager.list_registered_metrics()),
                "cache_size": len(self._metric_cache),
                "prometheus_available": self.metrics_manager._prometheus_available,
                "last_cache_clear": self._last_cache_clear
            }
        except Exception as e:
            logger.error(f"Error getting metrics summary: {e}")
            return {"error": str(e)}


# Global metrics collector instance
_validation_metrics_collector: Optional[ValidationMetricsCollector] = None


def get_validation_metrics_collector() -> ValidationMetricsCollector:
    """Get the global validation metrics collector instance"""
    global _validation_metrics_collector
    if _validation_metrics_collector is None:
        _validation_metrics_collector = ValidationMetricsCollector()
    return _validation_metrics_collector


def record_validation_event(
    event_type: ValidationEventType,
    threat_level: ThreatLevel = ThreatLevel.NONE,
    validation_rule: str = "unknown",
    client_ip_hash: str = "unknown",
    endpoint: str = "unknown",
    http_method: str = "unknown",
    user_agent_category: str = "unknown",
    processing_time_ms: float = 0.0,
    attack_categories: List[str] = None,
    rate_limit_rule: str = "unknown",
    additional_labels: Dict[str, str] = None
):
    """
    Convenience function to record validation events
    
    Args:
        event_type: Type of validation event
        threat_level: Security threat level
        validation_rule: Name of validation rule applied
        client_ip_hash: Hashed client IP address
        endpoint: Request endpoint
        http_method: HTTP method
        user_agent_category: Category of user agent
        processing_time_ms: Processing time in milliseconds
        attack_categories: List of detected attack categories
        rate_limit_rule: Name of rate limiting rule
        additional_labels: Additional metric labels
    """
    try:
        collector = get_validation_metrics_collector()
        metrics_data = ValidationMetricsData(
            event_type=event_type,
            threat_level=threat_level,
            validation_rule=validation_rule,
            client_ip_hash=client_ip_hash,
            endpoint=endpoint,
            http_method=http_method,
            user_agent_category=user_agent_category,
            processing_time_ms=processing_time_ms,
            attack_categories=attack_categories,
            rate_limit_rule=rate_limit_rule,
            additional_labels=additional_labels or {}
        )
        collector.record_validation_event(metrics_data)
    except Exception as e:
        logger.error(f"Error in record_validation_event convenience function: {e}")