"""
Metrics Manager for Safe Prometheus Metrics Registration.

This module provides safe metrics registration to prevent duplicate registration
warnings and handle metrics initialization gracefully.
"""

import logging
from typing import Dict, Any, Optional, Callable, Set
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class MetricsManager:
    """
    Manages Prometheus metrics registration safely to prevent duplicate warnings.
    """

    def __init__(self):
        self._registered_metrics: Set[str] = set()
        self._metrics_instances: Dict[str, Any] = {}
        self._prometheus_available = False
        self._registry = None

        try:
            from prometheus_client import REGISTRY, Counter, Histogram, Gauge
            self._prometheus_available = True
            self._registry = REGISTRY
            self._counter_class = Counter
            self._histogram_class = Histogram
            self._gauge_class = Gauge
            logger.debug("Prometheus client available for metrics")
        except ImportError:
            logger.warning("Prometheus client not available, using dummy metrics")
            self._setup_dummy_classes()

    def _setup_dummy_classes(self):
        """Setup dummy metric classes when Prometheus is not available."""
        class DummyMetric:
            def __init__(self, *args, **kwargs):
                pass

            def labels(self, **kwargs):
                return self

            def inc(self, amount=1):
                pass

            def observe(self, value):
                pass

            def set(self, value):
                pass

            def dec(self, amount=1):
                pass

        self._counter_class = DummyMetric
        self._histogram_class = DummyMetric
        self._gauge_class = DummyMetric

    def register_counter(
        self,
        name: str,
        description: str,
        labels: Optional[list] = None,
        registry=None
    ) -> Any:
        """Register a Counter metric safely."""
        return self._register_metric(
            name,
            lambda: self._counter_class(
                name,
                description,
                labels or [],
                registry=registry or self._registry
            )
        )

    def register_histogram(
        self,
        name: str,
        description: str,
        labels: Optional[list] = None,
        buckets=None,
        registry=None
    ) -> Any:
        """Register a Histogram metric safely."""
        kwargs = {
            'registry': registry or self._registry
        }
        if buckets is not None:
            kwargs['buckets'] = buckets

        return self._register_metric(
            name,
            lambda: self._histogram_class(
                name,
                description,
                labels or [],
                **kwargs
            )
        )

    def register_gauge(
        self,
        name: str,
        description: str,
        labels: Optional[list] = None,
        registry=None
    ) -> Any:
        """Register a Gauge metric safely."""
        return self._register_metric(
            name,
            lambda: self._gauge_class(
                name,
                description,
                labels or [],
                registry=registry or self._registry
            )
        )

    def _register_metric(self, name: str, factory: Callable) -> Any:
        """Register a metric safely, preventing duplicate registration warnings."""
        if name in self._registered_metrics:
            logger.debug(f"Metric {name} already registered, returning existing instance")
            return self._metrics_instances.get(name, self._create_dummy_metric())

        if not self._prometheus_available:
            logger.debug(f"Prometheus not available, returning dummy metric for {name}")
            dummy = self._create_dummy_metric()
            self._metrics_instances[name] = dummy
            self._registered_metrics.add(name)
            return dummy

        try:
            metric = factory()
            self._registered_metrics.add(name)
            self._metrics_instances[name] = metric
            logger.debug(f"Successfully registered metric: {name}")
            return metric
        except ValueError as e:
            if "Duplicated timeseries" in str(e) or "already registered" in str(e).lower():
                logger.warning(f"Metric {name} already registered by external system, using dummy metric")
                dummy = self._create_dummy_metric()
                self._metrics_instances[name] = dummy
                self._registered_metrics.add(name)
                return dummy
            else:
                logger.error(f"Failed to register metric {name}: {e}")
                dummy = self._create_dummy_metric()
                self._metrics_instances[name] = dummy
                return dummy
        except Exception as e:
            logger.error(f"Unexpected error registering metric {name}: {e}")
            dummy = self._create_dummy_metric()
            self._metrics_instances[name] = dummy
            return dummy

    def _create_dummy_metric(self) -> Any:
        """Create a dummy metric that does nothing."""
        class DummyMetric:
            def labels(self, **kwargs):
                return self

            def inc(self, amount=1):
                pass

            def observe(self, value):
                pass

            def set(self, value):
                pass

            def dec(self, amount=1):
                pass

        return DummyMetric()

    def is_registered(self, name: str) -> bool:
        """Check if a metric is already registered."""
        return name in self._registered_metrics

    def get_metric(self, name: str) -> Optional[Any]:
        """Get a registered metric by name."""
        return self._metrics_instances.get(name)

    def list_registered_metrics(self) -> list:
        """List all registered metric names."""
        return list(self._registered_metrics)

    def get_metrics_info(self) -> Dict[str, Any]:
        """Get information about registered metrics."""
        return {
            "prometheus_available": self._prometheus_available,
            "registered_count": len(self._registered_metrics),
            "registered_metrics": list(self._registered_metrics)
        }

    @contextmanager
    def safe_metrics_context(self):
        """Context manager for safe metrics operations."""
        try:
            yield self
        except Exception as e:
            logger.error(f"Error in metrics context: {e}")

    def clear_registry(self):
        """Clear the metrics registry (for testing)."""
        self._registered_metrics.clear()
        self._metrics_instances.clear()


# Global metrics manager instance
_metrics_manager: Optional[MetricsManager] = None


def get_metrics_manager() -> MetricsManager:
    """Get the global metrics manager instance."""
    global _metrics_manager
    if _metrics_manager is None:
        _metrics_manager = MetricsManager()
    return _metrics_manager


def register_service_metrics() -> Dict[str, Any]:
    """Register standard service metrics safely."""
    manager = get_metrics_manager()

    metrics = {}

    with manager.safe_metrics_context():
        metrics['request_count'] = manager.register_counter(
            'kari_service_requests_total',
            'Total service requests',
            ['service', 'method', 'status']
        )

        metrics['request_latency'] = manager.register_histogram(
            'kari_service_request_duration_seconds',
            'Service request latency',
            ['service', 'method']
        )

        metrics['service_health'] = manager.register_gauge(
            'kari_service_health_status',
            'Service health status (1=healthy, 0=unhealthy)',
            ['service']
        )

        metrics['dependency_status'] = manager.register_gauge(
            'kari_service_dependency_status',
            'Service dependency status (1=available, 0=unavailable)',
            ['service', 'dependency']
        )

    return metrics
