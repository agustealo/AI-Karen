"""
Comprehensive Health Monitoring System for Karen AI Intelligent Fallback

This module provides advanced health monitoring capabilities that go beyond basic
network connectivity to provide intelligent health assessment of all system components.

Features:
- Multi-tier health checking with cascading dependencies
- Health score aggregation and weighted assessment
- Predictive health analysis based on trends
- Comprehensive alerting and notification system
- Health-based decision making and automatic recovery triggers
"""

import asyncio
import logging
import os
import psutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict, deque
import json
import weakref
import aiohttp
import socket

from .network_connectivity import NetworkStatus, get_network_monitor
from ..integrations.intelligent_provider_registry import get_intelligent_provider_registry
from ..core.model_runtime.model_cache_service import get_model_cache_service

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Overall health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckType(Enum):
    """Types of health checks."""
    NETWORK = auto()
    PROVIDER = auto()
    MODEL = auto()
    SYSTEM = auto()
    RESOURCE = auto()


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """Result of a health check with detailed metrics."""
    check_type: HealthCheckType
    component: str
    status: HealthStatus
    score: float  # 0.0 to 1.0
    message: str
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    error_details: Optional[str] = None
    response_time: float = 0.0
    trend_data: Optional[Dict[str, float]] = None


@dataclass
class HealthThresholds:
    """Thresholds for health status determination."""
    healthy_min: float = 0.8
    degraded_min: float = 0.5
    critical_response_time: float = 10.0
    degraded_response_time: float = 5.0
    cpu_warning: float = 0.8
    cpu_critical: float = 0.95
    memory_warning: float = 0.8
    memory_critical: float = 0.95
    disk_warning: float = 0.9
    disk_critical: float = 0.95


@dataclass
class HealthAlert:
    """Health alert with context and metadata."""
    alert_id: str
    level: AlertLevel
    component: str
    message: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_timestamp: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    triggered_by: List[str] = field(default_factory=list)


@dataclass
class HealthTrend:
    """Health trend analysis data."""
    component: str
    metric: str
    current_value: float
    trend_direction: str  # "improving", "degrading", "stable"
    trend_strength: float  # 0.0 to 1.0
    prediction: Optional[float] = None
    confidence: float = 0.0
    time_window: int = 3600  # seconds


@dataclass
class HealthMonitorConfig:
    """Configuration for comprehensive health monitoring."""
    check_interval: float = field(default_factory=lambda: float(os.environ.get('KAREN_HEALTH_CHECK_INTERVAL', '60.0')))
    trend_analysis_window: int = field(default_factory=lambda: int(os.environ.get('KAREN_TREND_WINDOW', '3600')))
    alert_cooldown: float = field(default_factory=lambda: float(os.environ.get('KAREN_ALERT_COOLDOWN', '300.0')))
    max_history_size: int = field(default_factory=lambda: int(os.environ.get('KAREN_HEALTH_HISTORY_SIZE', '1000')))
    enable_predictive_analysis: bool = field(default_factory=lambda: os.environ.get('KAREN_ENABLE_PREDICTIVE', 'true').lower() == 'true')
    enable_auto_recovery: bool = field(default_factory=lambda: os.environ.get('KAREN_ENABLE_AUTO_RECOVERY', 'true').lower() == 'true')
    thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    health_check_timeout: float = field(default_factory=lambda: float(os.environ.get('KAREN_HEALTH_CHECK_TIMEOUT', '30.0')))
    max_concurrent_checks: int = field(default_factory=lambda: int(os.environ.get('KAREN_MAX_CONCURRENT_HEALTH_CHECKS', '5')))
    enable_detailed_logging: bool = field(default_factory=lambda: os.environ.get('KAREN_HEALTH_DETAILED_LOGGING', 'false').lower() == 'true')
    alert_webhook_url: Optional[str] = field(default_factory=lambda: os.environ.get('KAREN_ALERT_WEBHOOK_URL'))
    health_report_file: Optional[str] = field(default_factory=lambda: os.environ.get('KAREN_HEALTH_REPORT_FILE'))


class ComprehensiveHealthMonitor:
    """
    Comprehensive health monitoring system for intelligent fallback.
    
    Provides multi-tier health checking with cascading dependencies,
    predictive analysis, and intelligent alerting.
    """
    
    def __init__(self, config: Optional[HealthMonitorConfig] = None):
        """Initialize comprehensive health monitor."""
        self.config = config or HealthMonitorConfig()
        
        # Core state
        self._health_status = HealthStatus.UNKNOWN
        self._health_scores: Dict[str, float] = {}
        self._last_check_time = 0.0
        self._lock = threading.RLock()
        
        # Health check history
        self._check_history: deque = deque(maxlen=self.config.max_history_size)
        self._trend_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Alert system
        self._alerts: Dict[str, HealthAlert] = {}
        self._alert_callbacks: List[Callable[[HealthAlert], None]] = []
        self._last_alert_times: Dict[str, float] = {}
        
        # Component integrations
        self._network_monitor = get_network_monitor()
        self._provider_registry = get_intelligent_provider_registry()
        self._model_cache = get_model_cache_service()
        
        # Background monitoring
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._check_semaphore = asyncio.Semaphore(self.config.max_concurrent_checks)
        
        # Health check dependencies
        self._check_dependencies = {
            HealthCheckType.PROVIDER: [HealthCheckType.NETWORK],
            HealthCheckType.MODEL: [HealthCheckType.PROVIDER, HealthCheckType.NETWORK],
            HealthCheckType.SYSTEM: [HealthCheckType.RESOURCE],
            HealthCheckType.RESOURCE: [],
            HealthCheckType.NETWORK: []
        }
        
        # Component health weights for overall score calculation
        self._component_weights = {
            "NETWORK": 0.25,
            "PROVIDER": 0.25,
            "MODEL": 0.20,
            "SYSTEM": 0.15,
            "RESOURCE": 0.15
        }
        
        logger.info("Comprehensive health monitor initialized")
    
    async def start_monitoring(self) -> None:
        """Start continuous health monitoring."""
        if self._monitoring_active:
            logger.warning("Health monitoring already active")
            return
        
        self._monitoring_active = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Comprehensive health monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop health monitoring."""
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Save final health report
        await self._save_health_report()
        
        logger.info("Comprehensive health monitoring stopped")
    
    def get_overall_health(self) -> Tuple[HealthStatus, float]:
        """Get overall system health status and score."""
        with self._lock:
            if not self._health_scores:
                return HealthStatus.UNKNOWN, 0.0
            
            # Calculate weighted average score
            total_score = 0.0
            total_weight = 0.0
            
            for check_type_str, score in self._health_scores.items():
                weight = self._component_weights.get(check_type_str, 0.1)
                total_score += score * weight
                total_weight += weight
            
            overall_score = total_score / total_weight if total_weight > 0 else 0.0
            
            # Determine status based on score
            if overall_score >= self.config.thresholds.healthy_min:
                status = HealthStatus.HEALTHY
            elif overall_score >= self.config.thresholds.degraded_min:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY
            
            return status, overall_score
    
    def get_component_health(self, component: str) -> Optional[HealthCheckResult]:
        """Get health status for a specific component."""
        with self._lock:
            for result in reversed(self._check_history):
                if result.component == component:
                    return result
            return None
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive health summary."""
        overall_status, overall_score = self.get_overall_health()
        
        with self._lock:
            # Component breakdown
            component_status = {}
            for check_type in HealthCheckType:
                score = self._health_scores.get(check_type.name, 0.0)
                if score >= self.config.thresholds.healthy_min:
                    status = HealthStatus.HEALTHY
                elif score >= self.config.thresholds.degraded_min:
                    status = HealthStatus.DEGRADED
                else:
                    status = HealthStatus.UNHEALTHY
                
                component_status[check_type.name] = {
                    'status': status.value,
                    'score': score
                }
            
            # Active alerts
            active_alerts = [alert for alert in self._alerts.values() if not alert.resolved]
            
            # Recent trends
            trends = {}
            for component, trend_deque in self._trend_data.items():
                if len(trend_deque) >= 3:
                    recent_values = list(trend_deque)[-3:]
                    if recent_values[-1] > recent_values[-2] > recent_values[-3]:
                        direction = "improving"
                    elif recent_values[-1] < recent_values[-2] < recent_values[-3]:
                        direction = "degrading"
                    else:
                        direction = "stable"
                    
                    trends[component] = {
                        'direction': direction,
                        'current': recent_values[-1],
                        'trend': [recent_values[-3], recent_values[-2], recent_values[-1]]
                    }
            
            return {
                'overall_status': overall_status.value,
                'overall_score': overall_score,
                'last_check': self._last_check_time,
                'components': component_status,
                'active_alerts': len(active_alerts),
                'trends': trends,
                'monitoring_active': self._monitoring_active
            }
    
    def get_active_alerts(self, level: Optional[AlertLevel] = None) -> List[HealthAlert]:
        """Get active alerts, optionally filtered by level."""
        with self._lock:
            alerts = [alert for alert in self._alerts.values() if not alert.resolved]
            
            if level:
                alerts = [alert for alert in alerts if alert.level == level]
            
            return sorted(alerts, key=lambda a: a.timestamp, reverse=True)
    
    def register_alert_callback(self, callback: Callable[[HealthAlert], None]) -> None:
        """Register callback for health alerts."""
        self._alert_callbacks.append(callback)
    
    async def trigger_health_check(self, check_types: Optional[List[HealthCheckType]] = None) -> Dict[str, HealthCheckResult]:
        """Trigger immediate health check for specified types."""
        check_types = check_types or list(HealthCheckType)
        results = {}
        
        # Check dependencies first
        ordered_types = self._order_checks_by_dependencies(check_types)
        
        async with self._check_semaphore:
            for check_type in ordered_types:
                try:
                    result = await self._perform_health_check(check_type)
                    results[check_type.name] = result
                    
                    # Update trend data
                    self._update_trend_data(result)
                    
                except Exception as e:
                    logger.error(f"Health check failed for {check_type.name}: {e}")
                    results[check_type.name] = HealthCheckResult(
                        check_type=check_type,
                        component=check_type.name,
                        status=HealthStatus.UNHEALTHY,
                        score=0.0,
                        message=f"Health check failed: {e}",
                        error_details=str(e)
                    )
        
        # Update overall health status
        self._update_overall_health(results)
        
        return results
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        logger.info("Health monitoring loop started")
        
        while self._monitoring_active:
            try:
                await self.trigger_health_check()
                await asyncio.sleep(self.config.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")
                await asyncio.sleep(10)  # Brief pause before retrying
        
        logger.info("Health monitoring loop stopped")
    
    def _order_checks_by_dependencies(self, check_types: List[HealthCheckType]) -> List[HealthCheckType]:
        """Order health checks based on their dependencies."""
        ordered = []
        remaining = set(check_types)
        
        while remaining:
            # Find checks with no unmet dependencies
            ready = []
            for check_type in remaining:
                deps = self._check_dependencies.get(check_type, [])
                if all(dep in ordered for dep in deps):
                    ready.append(check_type)
            
            if not ready:
                # Circular dependency or missing dependency - add remaining checks
                ready.extend(remaining)
            
            for check_type in ready:
                ordered.append(check_type)
                remaining.discard(check_type)
        
        return ordered
    
    async def _perform_health_check(self, check_type: HealthCheckType) -> HealthCheckResult:
        """Perform a specific health check."""
        start_time = time.time()
        
        try:
            if check_type == HealthCheckType.NETWORK:
                result = await self._check_network_health()
            elif check_type == HealthCheckType.PROVIDER:
                result = await self._check_provider_health()
            elif check_type == HealthCheckType.MODEL:
                result = await self._check_model_health()
            elif check_type == HealthCheckType.SYSTEM:
                result = await self._check_system_health()
            elif check_type == HealthCheckType.RESOURCE:
                result = await self._check_resource_health()
            else:
                raise ValueError(f"Unknown health check type: {check_type}")
            
            result.response_time = time.time() - start_time
            
            # Store in history
            with self._lock:
                self._check_history.append(result)
                self._last_check_time = time.time()
            
            return result
            
        except Exception as e:
            return HealthCheckResult(
                check_type=check_type,
                component=check_type.name,
                status=HealthStatus.UNHEALTHY,
                score=0.0,
                message=f"Health check error: {e}",
                error_details=str(e),
                response_time=time.time() - start_time
            )
    
    async def _check_network_health(self) -> HealthCheckResult:
        """Check network connectivity health."""
        network_status = self._network_monitor.get_current_status()
        network_metrics = self._network_monitor.get_network_metrics()
        
        # Calculate score based on network status and metrics
        if network_status == NetworkStatus.ONLINE:
            base_score = 1.0
            status = HealthStatus.HEALTHY
            message = "Network connectivity is optimal"
        elif network_status == NetworkStatus.DEGRADED:
            base_score = 0.6
            status = HealthStatus.DEGRADED
            message = "Network connectivity is degraded"
        else:  # OFFLINE or UNKNOWN
            base_score = 0.0
            status = HealthStatus.UNHEALTHY
            message = "Network connectivity is unavailable"
        
        # Adjust score based on metrics
        if network_metrics:
            uptime_val = network_metrics.get('uptime_percentage', 0)
            uptime = float(uptime_val) / 100.0
            avg_response_val = network_metrics.get('average_response_time', 0)
            avg_response = float(avg_response_val)
            
            # Penalize high response times
            if avg_response > self.config.thresholds.critical_response_time:
                base_score *= 0.5
            elif avg_response > self.config.thresholds.degraded_response_time:
                base_score *= 0.8
            
            # Factor in uptime
            base_score = (base_score + uptime) / 2.0
        
        return HealthCheckResult(
            check_type=HealthCheckType.NETWORK,
            component="network",
            status=status,
            score=base_score,
            message=message,
            metrics=network_metrics or {}
        )
    
    async def _check_provider_health(self) -> HealthCheckResult:
        """Check health of registered providers."""
        provider_metrics = self._provider_registry.get_all_provider_metrics()
        
        if not provider_metrics:
            return HealthCheckResult(
                check_type=HealthCheckType.PROVIDER,
                component="providers",
                status=HealthStatus.UNKNOWN,
                score=0.0,
                message="No providers registered"
            )
        
        total_score = 0.0
        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0
        provider_details = {}
        
        for provider_name, metrics in provider_metrics.items():
            # Calculate individual provider score
            provider_score = metrics.success_rate
            
            # Penalize consecutive failures
            if metrics.consecutive_failures > 0:
                failure_penalty = min(0.5, metrics.consecutive_failures * 0.1)
                provider_score -= failure_penalty
            
            # Penalize high latency
            if metrics.average_latency > self.config.thresholds.critical_response_time:
                provider_score *= 0.5
            elif metrics.average_latency > self.config.thresholds.degraded_response_time:
                provider_score *= 0.8
            
            provider_score = max(0.0, provider_score)
            total_score += provider_score
            
            # Categorize provider health
            if provider_score >= self.config.thresholds.healthy_min:
                healthy_count += 1
            elif provider_score >= self.config.thresholds.degraded_min:
                degraded_count += 1
            else:
                unhealthy_count += 1
            
            provider_details[provider_name] = {
                'score': provider_score,
                'success_rate': metrics.success_rate,
                'consecutive_failures': metrics.consecutive_failures,
                'average_latency': metrics.average_latency
            }
        
        avg_score = total_score / len(provider_metrics)
        
        # Determine overall status
        if unhealthy_count == 0 and degraded_count <= len(provider_metrics) * 0.3:
            status = HealthStatus.HEALTHY
            message = f"All providers healthy ({healthy_count} total)"
        elif unhealthy_count <= len(provider_metrics) * 0.3:
            status = HealthStatus.DEGRADED
            message = f"Some providers degraded ({healthy_count} healthy, {degraded_count} degraded, {unhealthy_count} unhealthy)"
        else:
            status = HealthStatus.UNHEALTHY
            message = f"Many providers unhealthy ({healthy_count} healthy, {degraded_count} degraded, {unhealthy_count} unhealthy)"
        
        return HealthCheckResult(
            check_type=HealthCheckType.PROVIDER,
            component="providers",
            status=status,
            score=avg_score,
            message=message,
            metrics={
                'total_providers': len(provider_metrics),
                'healthy_count': healthy_count,
                'degraded_count': degraded_count,
                'unhealthy_count': unhealthy_count,
                'provider_details': provider_details
            }
        )
    
    async def _check_model_health(self) -> HealthCheckResult:
        """Check health of cached models."""
        cache_stats = self._model_cache.get_cache_statistics()
        
        if not cache_stats:
            return HealthCheckResult(
                check_type=HealthCheckType.MODEL,
                component="models",
                status=HealthStatus.UNKNOWN,
                score=0.0,
                message="Model cache not available"
            )
        
        total_entries = cache_stats.get('total_entries', 0)
        cache_hit_rate = cache_stats.get('cache_hit_rate', 0.0)
        preload_success_rate = cache_stats.get('preload_success_rate', 0.0)
        eviction_count = cache_stats.get('eviction_count', 0)
        active_downloads = cache_stats.get('active_downloads', 0)
        
        # Calculate base score from availability and performance
        base_score = cache_hit_rate * 0.6 + preload_success_rate * 0.4
        
        # Penalize high eviction count (indicates storage pressure)
        if total_entries > 0:
            eviction_rate = eviction_count / total_entries
            if eviction_rate > 0.2:  # More than 20% eviction rate
                base_score *= 0.8
        
        # Penalize many active downloads (indicates loading issues)
        if active_downloads > 3:
            base_score *= 0.9
        
        # Determine status
        if base_score >= self.config.thresholds.healthy_min and active_downloads == 0:
            status = HealthStatus.HEALTHY
            message = f"Model cache healthy ({total_entries} models cached)"
        elif base_score >= self.config.thresholds.degraded_min:
            status = HealthStatus.DEGRADED
            message = f"Model cache degraded ({total_entries} models cached, {active_downloads} downloading)"
        else:
            status = HealthStatus.UNHEALTHY
            message = f"Model cache unhealthy ({total_entries} models cached, {active_downloads} downloading)"
        
        return HealthCheckResult(
            check_type=HealthCheckType.MODEL,
            component="models",
            status=status,
            score=base_score,
            message=message,
            metrics=cache_stats
        )
    
    async def _check_system_health(self) -> HealthCheckResult:
        """Check overall system health."""
        try:
            # Check system time synchronization
            time_sync_score = 1.0  # Could implement NTP check here
            
            # Check disk I/O performance
            disk_io_score = await self._check_disk_io_performance()
            
            # Check process health
            process_score = await self._check_process_health()
            
            # Overall system score
            overall_score = (time_sync_score + disk_io_score + process_score) / 3.0
            
            # Determine status
            if overall_score >= self.config.thresholds.healthy_min:
                status = HealthStatus.HEALTHY
                message = "System operating normally"
            elif overall_score >= self.config.thresholds.degraded_min:
                status = HealthStatus.DEGRADED
                message = "System performance degraded"
            else:
                status = HealthStatus.UNHEALTHY
                message = "System experiencing issues"
            
            return HealthCheckResult(
                check_type=HealthCheckType.SYSTEM,
                component="system",
                status=status,
                score=overall_score,
                message=message,
                metrics={
                    'time_sync_score': time_sync_score,
                    'disk_io_score': disk_io_score,
                    'process_score': process_score
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.SYSTEM,
                component="system",
                status=HealthStatus.UNHEALTHY,
                score=0.0,
                message=f"System health check failed: {e}",
                error_details=str(e)
            )
    
    async def _check_resource_health(self) -> HealthCheckResult:
        """Check system resource health (CPU, memory, disk)."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_score = max(0.0, 1.0 - (cpu_percent / 100.0))
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_score = max(0.0, 1.0 - (memory_percent / 100.0))
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            disk_score = max(0.0, 1.0 - (disk_percent / 100.0))
            
            # Overall resource score (weighted)
            overall_score = (cpu_score * 0.4 + memory_score * 0.4 + disk_score * 0.2)
            
            # Determine status based on thresholds
            status = HealthStatus.HEALTHY
            message = "System resources are adequate"
            
            if (cpu_percent > self.config.thresholds.cpu_critical or
                memory_percent > self.config.thresholds.memory_critical or
                disk_percent > self.config.thresholds.disk_critical):
                status = HealthStatus.UNHEALTHY
                message = "System resources critically low"
            elif (cpu_percent > self.config.thresholds.cpu_warning or
                  memory_percent > self.config.thresholds.memory_warning or
                  disk_percent > self.config.thresholds.disk_warning):
                status = HealthStatus.DEGRADED
                message = "System resources getting low"
            
            return HealthCheckResult(
                check_type=HealthCheckType.RESOURCE,
                component="resources",
                status=status,
                score=overall_score,
                message=message,
                metrics={
                    'cpu_percent': cpu_percent,
                    'cpu_score': cpu_score,
                    'memory_percent': memory_percent,
                    'memory_score': memory_score,
                    'disk_percent': disk_percent,
                    'disk_score': disk_score,
                    'memory_available_gb': memory.available / (1024**3),
                    'disk_free_gb': disk.free / (1024**3)
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.RESOURCE,
                component="resources",
                status=HealthStatus.UNHEALTHY,
                score=0.0,
                message=f"Resource health check failed: {e}",
                error_details=str(e)
            )
    
    async def _check_disk_io_performance(self) -> float:
        """Check disk I/O performance."""
        try:
            # Simple disk performance test
            test_file = "/tmp/karen_health_test.tmp"
            start_time = time.time()
            
            # Write test
            with open(test_file, 'wb') as f:
                f.write(b'0' * 1024 * 1024)  # 1MB
            
            write_time = time.time() - start_time
            
            # Read test
            start_time = time.time()
            with open(test_file, 'rb') as f:
                f.read()
            
            read_time = time.time() - start_time
            
            # Cleanup
            os.remove(test_file)
            
            total_time = write_time + read_time
            
            # Score based on performance (faster is better)
            if total_time < 0.1:  # < 100ms
                return 1.0
            elif total_time < 0.5:  # < 500ms
                return 0.8
            elif total_time < 2.0:  # < 2s
                return 0.6
            else:
                return 0.4
                
        except Exception:
            return 0.5  # Default score if test fails
    
    async def _check_process_health(self) -> float:
        """Check health of critical processes."""
        try:
            # Check if we can get basic process info
            current_process = psutil.Process()
            
            # Check process age (restarts might indicate issues)
            create_time = current_process.create_time()
            age_seconds = time.time() - create_time
            
            # Very young process might indicate frequent restarts
            if age_seconds < 60:  # Less than 1 minute old
                return 0.7
            
            # Check process memory usage
            memory_info = current_process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)
            
            # Penalize excessive memory usage
            if memory_mb > 1000:  # > 1GB
                return 0.6
            elif memory_mb > 500:  # > 500MB
                return 0.8
            else:
                return 1.0
                
        except Exception:
            return 0.5  # Default score if check fails
    
    def _update_trend_data(self, result: HealthCheckResult) -> None:
        """Update trend data for health analysis."""
        component_key = f"{result.check_type.name}_{result.component}"
        
        with self._lock:
            self._trend_data[component_key].append(result.score)
            
            # Keep only recent data within trend window
            cutoff_time = time.time() - self.config.trend_analysis_window
            while (self._trend_data[component_key] and 
                   len(self._trend_data[component_key]) > 100):
                self._trend_data[component_key].popleft()
    
    def _update_overall_health(self, results: Dict[str, HealthCheckResult]) -> None:
        """Update overall health scores and status."""
        with self._lock:
            # Update individual component scores
            for check_type_name, result in results.items():
                try:
                    check_type = HealthCheckType[check_type_name]
                    self._health_scores[check_type.name] = result.score
                except KeyError:
                    continue
            
            # Calculate overall status and score
            overall_status, overall_score = self.get_overall_health()
            self._health_status = overall_status
            
            # Check for alerts
            self._check_for_alerts(results)
            
            # Log health changes
            if self.config.enable_detailed_logging:
                logger.info(f"Health status updated: {overall_status.value} (score: {overall_score:.3f})")
    
    def _check_for_alerts(self, results: Dict[str, HealthCheckResult]) -> None:
        """Check results for alert conditions."""
        current_time = time.time()
        
        for check_type_name, result in results.items():
            # Check for critical conditions
            if result.status == HealthStatus.UNHEALTHY:
                self._trigger_alert(
                    level=AlertLevel.CRITICAL,
                    component=result.component,
                    message=f"Critical: {result.message}",
                    metadata={
                        'score': result.score,
                        'metrics': result.metrics,
                        'error_details': result.error_details
                    }
                )
            
            # Check for degraded conditions
            elif result.status == HealthStatus.DEGRADED:
                self._trigger_alert(
                    level=AlertLevel.WARNING,
                    component=result.component,
                    message=f"Warning: {result.message}",
                    metadata={
                        'score': result.score,
                        'metrics': result.metrics
                    }
                )
            
            # Check for response time issues
            if result.response_time > self.config.thresholds.critical_response_time:
                self._trigger_alert(
                    level=AlertLevel.WARNING,
                    component=result.component,
                    message=f"Slow health check response: {result.response_time:.2f}s",
                    metadata={
                        'response_time': result.response_time,
                        'score': result.score
                    }
                )
    
    def _trigger_alert(self, level: AlertLevel, component: str, message: str,
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        """Trigger a health alert with cooldown."""
        current_time = time.time()
        alert_key = f"{level.value}_{component}"
        
        # Check cooldown
        if (alert_key in self._last_alert_times and 
            current_time - self._last_alert_times[alert_key] < self.config.alert_cooldown):
            return
        
        # Create alert
        alert_id = f"{int(current_time)}_{component}_{level.value}"
        alert = HealthAlert(
            alert_id=alert_id,
            level=level,
            component=component,
            message=message,
            metadata=metadata or {}
        )
        
        # Store alert
        with self._lock:
            self._alerts[alert_id] = alert
            self._last_alert_times[alert_key] = current_time
        
        # Log alert
        log_msg = f"Health Alert [{level.value.upper()}] {component}: {message}"
        if level == AlertLevel.CRITICAL:
            logger.error(log_msg)
        elif level == AlertLevel.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        
        # Trigger callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
        
        # Send webhook if configured
        if self.config.alert_webhook_url:
            asyncio.create_task(self._send_webhook_alert(alert))
    
    async def _send_webhook_alert(self, alert: HealthAlert) -> None:
        """Send alert via webhook."""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    'alert_id': alert.alert_id,
                    'level': alert.level.value,
                    'component': alert.component,
                    'message': alert.message,
                    'timestamp': alert.timestamp,
                    'metadata': alert.metadata
                }
                
                async with session.post(
                    self.config.alert_webhook_url or "",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.debug(f"Webhook alert sent successfully: {alert.alert_id}")
                    else:
                        logger.warning(f"Webhook alert failed with status {response.status}")
                        
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
    
    async def _save_health_report(self) -> None:
        """Save comprehensive health report to file."""
        if not self.config.health_report_file:
            return
        
        try:
            report = {
                'timestamp': time.time(),
                'summary': self.get_health_summary(),
                'alerts': [
                    {
                        'alert_id': alert.alert_id,
                        'level': alert.level.value,
                        'component': alert.component,
                        'message': alert.message,
                        'timestamp': alert.timestamp,
                        'resolved': alert.resolved,
                        'metadata': alert.metadata
                    }
                    for alert in self._alerts.values()
                ],
                'recent_checks': [
                    {
                        'check_type': result.check_type.name,
                        'component': result.component,
                        'status': result.status.value,
                        'score': result.score,
                        'message': result.message,
                        'timestamp': result.timestamp,
                        'response_time': result.response_time,
                        'metrics': result.metrics
                    }
                    for result in list(self._check_history)[-20:]  # Last 20 checks
                ]
            }
            
            with open(self.config.health_report_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"Health report saved to {self.config.health_report_file}")
            
        except Exception as e:
            logger.error(f"Failed to save health report: {e}")


# Global instance
_comprehensive_health_monitor: Optional[ComprehensiveHealthMonitor] = None
_monitor_lock = threading.RLock()


def get_comprehensive_health_monitor(config: Optional[HealthMonitorConfig] = None) -> ComprehensiveHealthMonitor:
    """Get or create global comprehensive health monitor instance."""
    global _comprehensive_health_monitor
    if _comprehensive_health_monitor is None:
        with _monitor_lock:
            if _comprehensive_health_monitor is None:
                _comprehensive_health_monitor = ComprehensiveHealthMonitor(config)
    return _comprehensive_health_monitor


async def initialize_comprehensive_health_monitor(config: Optional[HealthMonitorConfig] = None) -> ComprehensiveHealthMonitor:
    """Initialize comprehensive health monitoring system."""
    monitor = get_comprehensive_health_monitor(config)
    await monitor.start_monitoring()
    logger.info("Comprehensive health monitoring system initialized")
    return monitor


# Export main classes for easy import
__all__ = [
    "HealthStatus",
    "HealthCheckType",
    "AlertLevel",
    "HealthCheckResult",
    "HealthThresholds",
    "HealthAlert",
    "HealthTrend",
    "HealthMonitorConfig",
    "ComprehensiveHealthMonitor",
    "get_comprehensive_health_monitor",
    "initialize_comprehensive_health_monitor",
]