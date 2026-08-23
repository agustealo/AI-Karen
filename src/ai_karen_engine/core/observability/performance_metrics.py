"""
Performance metrics collection and monitoring system.

This module provides performance metrics collection with observability integration.
SQLite-backed persistence has been removed in favor of core/observability.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class MetricType(Enum):
    """Types of performance metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PerformanceMetric:
    """Enhanced performance metric data model."""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime
    service_name: str
    tags: Dict[str, str] = field(default_factory=dict)
    unit: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "metric_type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "service_name": self.service_name,
            "tags": self.tags,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass
class SystemMetrics:
    """System-wide performance metrics."""
    timestamp: datetime
    cpu_percent: float
    memory_usage: int
    memory_percent: float
    disk_usage: int
    disk_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    load_average: Tuple[float, float, float]
    process_count: int
    thread_count: int

    def to_metrics(self) -> List[PerformanceMetric]:
        """Convert to list of PerformanceMetric objects."""
        return [
            PerformanceMetric("system.cpu.percent", self.cpu_percent, MetricType.GAUGE, self.timestamp, "system", unit="%"),
            PerformanceMetric("system.memory.usage", self.memory_usage, MetricType.GAUGE, self.timestamp, "system", unit="bytes"),
            PerformanceMetric("system.memory.percent", self.memory_percent, MetricType.GAUGE, self.timestamp, "system", unit="%"),
            PerformanceMetric("system.disk.usage", self.disk_usage, MetricType.GAUGE, self.timestamp, "system", unit="bytes"),
            PerformanceMetric("system.disk.percent", self.disk_percent, MetricType.GAUGE, self.timestamp, "system", unit="%"),
            PerformanceMetric("system.network.bytes_sent", self.network_bytes_sent, MetricType.COUNTER, self.timestamp, "system", unit="bytes"),
            PerformanceMetric("system.network.bytes_recv", self.network_bytes_recv, MetricType.COUNTER, self.timestamp, "system", unit="bytes"),
            PerformanceMetric("system.load.1min", self.load_average[0], MetricType.GAUGE, self.timestamp, "system"),
            PerformanceMetric("system.load.5min", self.load_average[1], MetricType.GAUGE, self.timestamp, "system"),
            PerformanceMetric("system.load.15min", self.load_average[2], MetricType.GAUGE, self.timestamp, "system"),
            PerformanceMetric("system.processes.count", self.process_count, MetricType.GAUGE, self.timestamp, "system"),
            PerformanceMetric("system.threads.count", self.thread_count, MetricType.GAUGE, self.timestamp, "system"),
        ]


@dataclass
class ServiceMetrics:
    """Service-specific performance metrics."""
    service_name: str
    timestamp: datetime
    cpu_percent: float
    memory_usage: int
    memory_percent: float
    io_read_bytes: int
    io_write_bytes: int
    thread_count: int
    open_files: int
    network_connections: int
    response_time: Optional[float] = None
    request_count: int = 0
    error_count: int = 0

    def to_metrics(self) -> List[PerformanceMetric]:
        """Convert to list of PerformanceMetric objects."""
        metrics = [
            PerformanceMetric(f"service.{self.service_name}.cpu.percent", self.cpu_percent, MetricType.GAUGE, self.timestamp, self.service_name, unit="%"),
            PerformanceMetric(f"service.{self.service_name}.memory.usage", self.memory_usage, MetricType.GAUGE, self.timestamp, self.service_name, unit="bytes"),
            PerformanceMetric(f"service.{self.service_name}.memory.percent", self.memory_percent, MetricType.GAUGE, self.timestamp, self.service_name, unit="%"),
            PerformanceMetric(f"service.{self.service_name}.io.read_bytes", self.io_read_bytes, MetricType.COUNTER, self.timestamp, self.service_name, unit="bytes"),
            PerformanceMetric(f"service.{self.service_name}.io.write_bytes", self.io_write_bytes, MetricType.COUNTER, self.timestamp, self.service_name, unit="bytes"),
            PerformanceMetric(f"service.{self.service_name}.threads.count", self.thread_count, MetricType.GAUGE, self.timestamp, self.service_name),
            PerformanceMetric(f"service.{self.service_name}.files.open", self.open_files, MetricType.GAUGE, self.timestamp, self.service_name),
            PerformanceMetric(f"service.{self.service_name}.network.connections", self.network_connections, MetricType.GAUGE, self.timestamp, self.service_name),
            PerformanceMetric(f"service.{self.service_name}.requests.count", self.request_count, MetricType.COUNTER, self.timestamp, self.service_name),
            PerformanceMetric(f"service.{self.service_name}.errors.count", self.error_count, MetricType.COUNTER, self.timestamp, self.service_name),
        ]
        if self.response_time is not None:
            metrics.append(PerformanceMetric(f"service.{self.service_name}.response_time", self.response_time, MetricType.TIMER, self.timestamp, self.service_name, unit="seconds"))
        return metrics


class MetricsCollector:
    """Collects performance metrics from various sources."""

    def __init__(self):
        self.custom_collectors: Dict[str, Callable] = {}

    def register_collector(self, name: str, collector_func: Callable):
        """Register a custom metrics collector."""
        self.custom_collectors[name] = collector_func
        logger.info(f"Registered custom collector: {name}")

    async def collect_system_metrics(self) -> SystemMetrics:
        """Collect system-wide performance metrics."""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            network = psutil.net_io_counters()
            try:
                load_avg = psutil.getloadavg()
            except AttributeError:
                load_avg = (0.0, 0.0, 0.0)
            process_count = len(psutil.pids())
            thread_count = 0
            try:
                for p in psutil.process_iter(["num_threads"]):
                    try:
                        thread_count += p.info["num_threads"] or 0
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception:
                pass

            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_usage=memory.used,
                memory_percent=memory.percent,
                disk_usage=disk.used,
                disk_percent=disk.percent,
                network_bytes_sent=network.bytes_sent,
                network_bytes_recv=network.bytes_recv,
                load_average=load_avg,
                process_count=process_count,
                thread_count=thread_count,
            )
        except Exception as e:
            logger.warning(f"Failed to collect system metrics: {e}")
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=0.0,
                memory_usage=0,
                memory_percent=0.0,
                disk_usage=0,
                disk_percent=0.0,
                network_bytes_sent=0,
                network_bytes_recv=0,
                load_average=(0.0, 0.0, 0.0),
                process_count=0,
                thread_count=0,
            )

    async def collect_service_metrics(self, service_name: str, pid: Optional[int] = None) -> Optional[ServiceMetrics]:
        """Collect metrics for a specific service."""
        try:
            import psutil
            if pid:
                process = psutil.Process(pid)
            else:
                processes = [p for p in psutil.process_iter(["pid", "name"]) if service_name in p.info["name"]]
                if not processes:
                    return None
                process = processes[0]

            proc_info = process.as_dict([
                "cpu_percent", "memory_info", "memory_percent",
                "io_counters", "num_threads", "num_fds", "connections"
            ])

            io_counters = proc_info.get("io_counters")
            io_read = io_counters.read_bytes if io_counters else 0
            io_write = io_counters.write_bytes if io_counters else 0

            return ServiceMetrics(
                service_name=service_name,
                timestamp=datetime.now(),
                cpu_percent=proc_info["cpu_percent"] or 0.0,
                memory_usage=proc_info["memory_info"].rss if proc_info.get("memory_info") else 0,
                memory_percent=proc_info["memory_percent"] or 0.0,
                io_read_bytes=io_read,
                io_write_bytes=io_write,
                thread_count=proc_info.get("num_threads") or 0,
                open_files=proc_info.get("num_fds") or 0,
                network_connections=len(proc_info.get("connections") or []),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
        except Exception as e:
            logger.debug(f"Error collecting metrics for {service_name}: {e}")
            return None

    async def collect_custom_metrics(self) -> List[PerformanceMetric]:
        """Collect metrics from custom collectors."""
        metrics = []
        for name, collector in self.custom_collectors.items():
            try:
                custom_metrics = await collector()
                if isinstance(custom_metrics, list):
                    metrics.extend(custom_metrics)
                elif isinstance(custom_metrics, PerformanceMetric):
                    metrics.append(custom_metrics)
            except Exception as e:
                logger.error(f"Error in custom collector {name}: {e}")
        return metrics


class PerformanceDashboard:
    """Real-time performance dashboard."""

    def __init__(self):
        self.dashboard_data: Dict[str, Any] = {}
        self.update_interval = 30
        self.running = False
        self.update_task: Optional[asyncio.Task] = None

    async def start(self):
        if self.running:
            return
        self.running = True
        self.update_task = asyncio.create_task(self._update_loop())
        logger.info("Performance dashboard started")

    async def stop(self):
        self.running = False
        if self.update_task:
            self.update_task.cancel()
            try:
                await self.update_task
            except asyncio.CancelledError:
                pass
        logger.info("Performance dashboard stopped")

    async def _update_loop(self):
        while self.running:
            try:
                await self._update_dashboard_data()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error updating dashboard: {e}")
                await asyncio.sleep(self.update_interval)

    async def _update_dashboard_data(self):
        self.dashboard_data = {
            "last_updated": datetime.now().isoformat(),
            "system_overview": {},
            "services": {},
            "alerts": [],
        }

    async def get_dashboard_data(self) -> Dict[str, Any]:
        return self.dashboard_data.copy()


class PerformanceBenchmark:
    """Performance benchmarking tools."""

    def __init__(self):
        self.benchmarks: Dict[str, Dict[str, Any]] = {}

    async def create_baseline(
        self,
        name: str,
        duration_minutes: int = 60,
        services: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        baseline = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "duration_minutes": duration_minutes,
            "services": services,
            "metrics": {},
            "total_samples": 0,
            "unique_metrics": 0,
        }
        self.benchmarks[name] = baseline
        logger.info(f"Created performance baseline '{name}'")
        return baseline

    def get_benchmark(self, name: str) -> Optional[Dict[str, Any]]:
        return self.benchmarks.get(name)

    def list_benchmarks(self) -> List[str]:
        return list(self.benchmarks.keys())

    async def compare_to_baseline(
        self,
        baseline_name: str,
        duration_minutes: int = 60,
    ) -> Dict[str, Any]:
        if baseline_name not in self.benchmarks:
            raise ValueError(f"Baseline '{baseline_name}' not found")
        return {
            "baseline_name": baseline_name,
            "comparison_time": datetime.now().isoformat(),
            "baseline_stats": self.benchmarks[baseline_name].get("metrics", {}),
            "current_stats": {},
            "differences": {},
            "summary": {
                "improved_metrics": 0,
                "degraded_metrics": 0,
                "stable_metrics": 0,
            },
        }


class PerformanceMonitoringSystem:
    """Main performance monitoring system coordinator."""

    def __init__(
        self,
        collection_interval: int = 30,
    ):
        self.collection_interval = collection_interval
        self.storage = _InMemoryMetricsStore()
        self.collector = MetricsCollector()
        self.regression_detector = _InMemoryRegressionDetector(self.storage)
        self.dashboard = PerformanceDashboard()
        self.benchmark = PerformanceBenchmark()

        self.running = False
        self.collection_task: Optional[asyncio.Task] = None
        self.regression_task: Optional[asyncio.Task] = None

        logger.info("Performance monitoring system initialized")

    async def start(self):
        if self.running:
            return
        self.running = True
        await self.dashboard.start()
        self.collection_task = asyncio.create_task(self._collection_loop())
        self.regression_task = asyncio.create_task(self._regression_loop())
        logger.info("Performance monitoring system started")

    async def stop(self):
        self.running = False
        await self.dashboard.stop()
        for task in [self.collection_task, self.regression_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Performance monitoring system stopped")

    async def _collection_loop(self):
        while self.running:
            try:
                await self._collect_all_metrics()
                await asyncio.sleep(self.collection_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in metrics collection: {e}")
                await asyncio.sleep(self.collection_interval)

    async def _regression_loop(self):
        while self.running:
            try:
                await asyncio.sleep(600)
                regressions = await self.regression_detector.detect_regressions(
                    self.storage.all_metrics()
                )
                if regressions:
                    logger.warning(f"Detected {len(regressions)} performance regressions")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in regression detection: {e}")

    async def _collect_all_metrics(self):
        all_metrics: List[PerformanceMetric] = []
        try:
            system_metrics = await self.collector.collect_system_metrics()
            all_metrics.extend(system_metrics.to_metrics())
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")

        known_services = ["main", "api", "auth", "llm", "database", "memory"]
        for service_name in known_services:
            try:
                service_metrics = await self.collector.collect_service_metrics(service_name)
                if service_metrics:
                    all_metrics.extend(service_metrics.to_metrics())
            except Exception as e:
                logger.debug(f"Error collecting metrics for {service_name}: {e}")

        try:
            custom_metrics = await self.collector.collect_custom_metrics()
            all_metrics.extend(custom_metrics)
        except Exception as e:
            logger.error(f"Error collecting custom metrics: {e}")

        if all_metrics:
            await self.storage.store_metrics(all_metrics)
            logger.debug(f"Stored {len(all_metrics)} performance metrics")

    async def get_dashboard_data(self) -> Dict[str, Any]:
        return await self.dashboard.get_dashboard_data()

    async def create_benchmark(self, name: str, **kwargs) -> Dict[str, Any]:
        return await self.benchmark.create_baseline(name, **kwargs)

    async def compare_to_benchmark(self, name: str, **kwargs) -> Dict[str, Any]:
        return await self.benchmark.compare_to_baseline(name, **kwargs)

    def register_custom_collector(self, name: str, collector_func: Callable):
        self.collector.register_collector(name, collector_func)

    async def cleanup_old_data(self, retention_days: int = 30):
        return await self.storage.cleanup_old_metrics(retention_days)


class _InMemoryMetricsStore:
    """In-memory metrics store for backward compatibility."""

    def __init__(self, max_metrics: int = 10000):
        self._metrics: List[PerformanceMetric] = []
        self._alerts: List[Any] = []
        self._baselines: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self.max_metrics = max_metrics

    async def store_metrics(self, metrics: List[PerformanceMetric]):
        self._metrics.extend(metrics)
        if len(self._metrics) > self.max_metrics:
            self._metrics = self._metrics[-self.max_metrics:]

    async def get_metrics(
        self,
        metric_name: Optional[str] = None,
        service_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[PerformanceMetric]:
        result = list(self._metrics)
        if metric_name:
            result = [m for m in result if m.name == metric_name]
        if service_name:
            result = [m for m in result if m.service_name == service_name]
        if start_time:
            result = [m for m in result if m.timestamp >= start_time]
        if end_time:
            result = [m for m in result if m.timestamp <= end_time]
        result.sort(key=lambda m: m.timestamp, reverse=True)
        return result[:limit]

    async def store_baseline(self, metric_name: str, service_name: str, baseline_value: float, sample_count: int):
        self._baselines[(metric_name, service_name)] = (baseline_value, sample_count)

    async def get_baseline(self, metric_name: str, service_name: str) -> Optional[Tuple[float, int]]:
        return self._baselines.get((metric_name, service_name))

    async def store_alert(self, alert: Any):
        self._alerts.append(alert)

    async def get_alerts(self, enabled_only: bool = True) -> List[Any]:
        if enabled_only:
            return [a for a in self._alerts if getattr(a, "enabled", True)]
        return list(self._alerts)

    async def update_alert_trigger(self, alert_id: str, triggered_at: datetime):
        for alert in self._alerts:
            if getattr(alert, "id", None) == alert_id:
                alert.last_triggered = triggered_at
                alert.trigger_count = getattr(alert, "trigger_count", 0) + 1

    async def cleanup_old_metrics(self, retention_days: int = 30):
        cutoff = datetime.now() - timedelta(days=retention_days)
        old_count = len(self._metrics)
        self._metrics = [m for m in self._metrics if m.timestamp >= cutoff]
        deleted = old_count - len(self._metrics)
        logger.info(f"Cleaned up {deleted} old metrics records")
        return deleted

    def all_metrics(self) -> List[PerformanceMetric]:
        return list(self._metrics)


class _InMemoryRegressionDetector:
    """In-memory regression detector for backward compatibility."""

    def __init__(self, store: _InMemoryMetricsStore):
        from ai_karen_engine.core.observability.regression_detection import RegressionDetector
        self._detector = RegressionDetector()
        self._store = store

    async def detect_regressions(
        self,
        lookback_hours: int = 24,
        min_samples: int = 10,
    ) -> List[Any]:
        return await self._detector.detect_regressions(
            self._store.all_metrics(),
            lookback_hours=lookback_hours,
            min_samples=min_samples,
        )


class PerformanceMetrics:
    """Lightweight async wrapper exposing initialize(), record_metric(), start_collection().

    This wrapper logs metrics through observability. It no longer depends on
    SQLite-backed metrics storage.
    """

    def __init__(self, service_name: str = "system"):
        self.service_name = service_name
        self._collecting = False
        self._thread: Optional[threading.Thread] = None

    async def initialize(self) -> None:
        logger.info(f"PerformanceMetrics initialized for {self.service_name}")

    async def record_metric(
        self,
        name: str,
        value: float,
        *,
        service_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        unit: str = "",
    ) -> None:
        metric = PerformanceMetric(
            name=name,
            value=float(value),
            metric_type=MetricType.GAUGE,
            timestamp=datetime.now(),
            service_name=service_name or self.service_name,
            tags=tags or {},
            unit=unit,
        )
        try:
            logger.info(json.dumps({"metric": metric.to_dict()}))
        except Exception:
            logger.info(f"metric {name}={value}")

    async def start_collection(self, interval_seconds: int = 0) -> None:
        if interval_seconds <= 0 or self._collecting:
            return
        self._collecting = True

        def _loop():
            collector = MetricsCollector()
            while self._collecting:
                try:
                    sysm = asyncio.run(collector.collect_system_metrics())
                    for m in sysm.to_metrics():
                        asyncio.run(self.record_metric(m.name, m.value, service_name=m.service_name, unit=m.unit))
                except Exception:
                    pass
                time.sleep(interval_seconds)

        self._thread = threading.Thread(target=_loop, name="perf-metrics", daemon=True)
        self._thread.start()

    async def shutdown(self) -> None:
        self._collecting = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info(f"PerformanceMetrics shutdown for {self.service_name}")


# Global instance
_monitoring_system: Optional[PerformanceMonitoringSystem] = None


def get_performance_monitoring_system() -> PerformanceMonitoringSystem:
    """Get the global performance monitoring system instance."""
    global _monitoring_system
    if _monitoring_system is None:
        _monitoring_system = PerformanceMonitoringSystem()
    return _monitoring_system


async def initialize_performance_monitoring() -> PerformanceMonitoringSystem:
    """Initialize and start the performance monitoring system."""
    system = get_performance_monitoring_system()
    await system.start()
    return system


async def shutdown_performance_monitoring() -> None:
    """Shutdown the performance monitoring system."""
    global _monitoring_system
    if _monitoring_system:
        await _monitoring_system.stop()
        _monitoring_system = None
