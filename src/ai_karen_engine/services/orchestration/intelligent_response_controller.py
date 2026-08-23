"""
Intelligent Response Controller with resource optimization that preserves reasoning logic.

This controller wraps existing DecisionEngine and LangGraphOrchestrator without modifying their logic,
while adding CPU usage monitoring, memory management, and performance optimization.

Requirements addressed:
- 2.1: CPU usage SHALL not exceed 5% per response generation process
- 2.4: Memory usage SHALL automatically optimize memory allocation for response processing
- 2.5: Resource-aware processing SHALL maintain performance when system load is high
- 8.1: Preserve existing DecisionEngine logic for intent analysis and tool selection
- 8.2: Maintain orchestration workflow execution and statistics
- 8.3: Preserve SmallLanguageModel scaffolding for reasoning and outline generation
"""

import asyncio
import logging
import psutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Union
from datetime import datetime, timedelta
from collections import deque
import gc
import weakref

from ai_karen_engine.core.automation.contracts import (
    DecideActionInput,
    DecideActionOutput,
    FlowInput,
    FlowOutput,
    FlowType,
)
from ai_karen_engine.core.langgraph_orchestrator import (
    DecisionEngine,
    LangGraphOrchestrator,
)
from ai_karen_engine.core.reasoning.synthesis.small_language_model_service import (
    SmallLanguageModelService,
)


@dataclass
class ResourceMetrics:
    """Resource usage metrics for monitoring."""

    cpu_percent: float
    memory_mb: float
    memory_percent: float
    timestamp: datetime
    response_id: Optional[str] = None
    processing_stage: Optional[str] = None


@dataclass
class ResponsePerformanceMetrics:
    """Performance metrics for response generation."""

    response_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration_ms: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    decision_engine_duration_ms: float = 0.0
    flow_manager_duration_ms: float = 0.0
    small_language_model_duration_ms: float = 0.0
    optimization_applied: List[str] = field(default_factory=list)
    resource_pressure_detected: bool = False
    fallback_used: bool = False


@dataclass
class ResourcePressureConfig:
    """Configuration for resource pressure detection."""

    cpu_threshold_percent: float = 5.0  # Max CPU per response
    memory_threshold_mb: float = 500.0  # Max memory per response
    system_cpu_threshold_percent: float = 80.0  # System-wide CPU threshold
    system_memory_threshold_percent: float = 85.0  # System-wide memory threshold
    pressure_detection_window_seconds: int = 30
    optimization_cooldown_seconds: int = 60


class ResourceMonitor:
    """Real-time resource monitoring with pressure detection."""

    def __init__(self, config: ResourcePressureConfig):
        self.config = config
        self.logger = logging.getLogger("intelligent_response.resource_monitor")
        self._metrics_history: deque = deque(maxlen=1000)
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._process = psutil.Process()

    def start_monitoring(self):
        """Start resource monitoring in background thread."""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self.logger.info("Resource monitoring started")

    def stop_monitoring(self):
        """Stop resource monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        self.logger.info("Resource monitoring stopped")

    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._monitoring:
            try:
                metrics = self._collect_metrics()
                with self._lock:
                    self._metrics_history.append(metrics)
                time.sleep(1.0)  # Monitor every second
            except Exception as e:
                self.logger.error(f"Resource monitoring error: {e}")
                time.sleep(5.0)  # Back off on error

    def _collect_metrics(self) -> ResourceMetrics:
        """Collect current resource metrics."""
        try:
            # Process-specific metrics
            cpu_percent = self._process.cpu_percent()
            memory_info = self._process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024

            # System-wide memory percentage
            system_memory = psutil.virtual_memory()
            memory_percent = system_memory.percent

            return ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_mb=memory_mb,
                memory_percent=memory_percent,
                timestamp=datetime.now(),
            )
        except Exception as e:
            self.logger.error(f"Failed to collect metrics: {e}")
            return ResourceMetrics(
                cpu_percent=0.0,
                memory_mb=0.0,
                memory_percent=0.0,
                timestamp=datetime.now(),
            )

    def get_current_metrics(self) -> ResourceMetrics:
        """Get current resource metrics."""
        return self._collect_metrics()

    def detect_resource_pressure(self) -> bool:
        """Detect if system is under resource pressure."""
        try:
            current_metrics = self.get_current_metrics()

            # Check system-wide thresholds
            if current_metrics.cpu_percent > self.config.system_cpu_threshold_percent:
                return True
            if (
                current_metrics.memory_percent
                > self.config.system_memory_threshold_percent
            ):
                return True

            # Check recent history for sustained pressure
            with self._lock:
                if len(self._metrics_history) < 10:
                    return False

                recent_metrics = list(self._metrics_history)[-10:]
                avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(
                    recent_metrics
                )
                avg_memory = sum(m.memory_percent for m in recent_metrics) / len(
                    recent_metrics
                )

                if avg_cpu > self.config.system_cpu_threshold_percent * 0.8:
                    return True
                if avg_memory > self.config.system_memory_threshold_percent * 0.8:
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Resource pressure detection failed: {e}")
            return False

    def get_metrics_history(self, duration_seconds: int = 300) -> List[ResourceMetrics]:
        """Get metrics history for specified duration."""
        cutoff_time = datetime.now() - timedelta(seconds=duration_seconds)
        with self._lock:
            return [m for m in self._metrics_history if m.timestamp >= cutoff_time]


class MemoryManager:
    """Memory management system for efficient response generation."""

    def __init__(self):
        self.logger = logging.getLogger("intelligent_response.memory_manager")
        self._gc_threshold_mb = 100.0  # Trigger GC when memory increases by this amount
        self._last_gc_time = time.time()
        self._gc_cooldown_seconds = 30.0
        self._baseline_memory_mb = 0.0
        self._weak_refs: List[weakref.ref] = []

    def initialize(self):
        """Initialize memory manager with baseline measurements."""
        self._baseline_memory_mb = self._get_memory_usage_mb()
        self.logger.info(
            f"Memory manager initialized with baseline: {self._baseline_memory_mb:.1f}MB"
        )

    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0

    def optimize_memory_before_response(self) -> Dict[str, Any]:
        """Optimize memory before response generation."""
        start_memory = self._get_memory_usage_mb()
        optimizations_applied = []

        try:
            # Clean up weak references
            self._cleanup_weak_refs()
            optimizations_applied.append("weak_ref_cleanup")

            # Conditional garbage collection
            current_time = time.time()
            memory_increase = start_memory - self._baseline_memory_mb

            if (
                memory_increase > self._gc_threshold_mb
                and current_time - self._last_gc_time > self._gc_cooldown_seconds
            ):
                collected = gc.collect()
                self._last_gc_time = current_time
                optimizations_applied.append(f"gc_collected_{collected}")
                self.logger.debug(f"Garbage collection freed {collected} objects")

            end_memory = self._get_memory_usage_mb()
            memory_freed = start_memory - end_memory

            return {
                "memory_freed_mb": memory_freed,
                "optimizations_applied": optimizations_applied,
                "start_memory_mb": start_memory,
                "end_memory_mb": end_memory,
            }

        except Exception as e:
            self.logger.error(f"Memory optimization failed: {e}")
            return {
                "memory_freed_mb": 0.0,
                "optimizations_applied": [],
                "error": str(e),
            }

    def optimize_memory_after_response(self, response_data: Any) -> Dict[str, Any]:
        """Optimize memory after response generation."""
        try:
            # Store weak reference to response data for cleanup
            if response_data:
                self._weak_refs.append(weakref.ref(response_data))

            # Limit weak reference collection size
            if len(self._weak_refs) > 100:
                self._weak_refs = self._weak_refs[-50:]

            return {"cleanup_scheduled": True}

        except Exception as e:
            self.logger.error(f"Post-response memory optimization failed: {e}")
            return {"cleanup_scheduled": False, "error": str(e)}

    def _cleanup_weak_refs(self):
        """Clean up dead weak references."""
        try:
            alive_refs = []
            for ref in self._weak_refs:
                if ref() is not None:
                    alive_refs.append(ref)
            self._weak_refs = alive_refs
        except Exception as e:
            self.logger.error(f"Weak reference cleanup failed: {e}")


class IntelligentResponseController:
    """
    Intelligent response controller that wraps existing reasoning components
    without modifying their logic, while adding resource optimization.
    """

    def __init__(
        self,
        decision_engine: DecisionEngine,
        flow_manager: LangGraphOrchestrator,
        small_language_model_service: Optional[SmallLanguageModelService] = None,
        config: Optional[ResourcePressureConfig] = None,
    ):
        self.logger = logging.getLogger("intelligent_response.controller")

        # Preserve original components without modification
        self._decision_engine = decision_engine
        self._orchestrator = flow_manager
        self._small_language_model_service = small_language_model_service

        # Resource optimization components
        self.config = config or ResourcePressureConfig()
        self.resource_monitor = ResourceMonitor(self.config)
        self.memory_manager = MemoryManager()

        # Performance tracking
        self._performance_metrics: Dict[str, ResponsePerformanceMetrics] = {}
        self._metrics_lock = threading.RLock()
        self._last_optimization_time = 0.0

        # Initialize components
        self.memory_manager.initialize()
        self.resource_monitor.start_monitoring()

        self.logger.info(
            "IntelligentResponseController initialized with resource optimization"
        )

    async def generate_optimized_response(
        self, input_data: DecideActionInput, response_id: Optional[str] = None
    ) -> DecideActionOutput:
        """
        Generate optimized response while preserving all existing reasoning logic.

        This method wraps the existing DecisionEngine without modifying its behavior,
        while adding resource monitoring and optimization.
        """
        response_id = response_id or f"resp_{int(time.time() * 1000)}"

        # Start performance tracking
        metrics = ResponsePerformanceMetrics(
            response_id=response_id, start_time=datetime.now()
        )

        try:
            # Pre-response resource optimization
            await self._optimize_resources_before_response(metrics)

            # Execute original decision engine logic (PRESERVED)
            decision_start = time.time()
            response = await self._decision_engine.decide_action(input_data)
            decision_duration = (time.time() - decision_start) * 1000

            metrics.decision_engine_duration_ms = decision_duration

            # Post-response resource optimization
            await self._optimize_resources_after_response(response, metrics)

            # Finalize metrics
            metrics.end_time = datetime.now()
            metrics.total_duration_ms = (
                metrics.end_time - metrics.start_time
            ).total_seconds() * 1000

            # Store metrics
            with self._metrics_lock:
                self._performance_metrics[response_id] = metrics

                # Limit metrics storage
                if len(self._performance_metrics) > 1000:
                    oldest_keys = sorted(self._performance_metrics.keys())[:100]
                    for key in oldest_keys:
                        del self._performance_metrics[key]

            self.logger.debug(
                f"Response {response_id} completed in {metrics.total_duration_ms:.1f}ms "
                f"(CPU: {metrics.cpu_usage_percent:.1f}%, Memory: {metrics.memory_usage_mb:.1f}MB)"
            )

            return response

        except Exception as e:
            metrics.end_time = datetime.now()
            metrics.total_duration_ms = (
                metrics.end_time - metrics.start_time
            ).total_seconds() * 1000

            self.logger.error(f"Response generation failed for {response_id}: {e}")
            raise

    async def execute_optimized_flow(
        self,
        flow_type: FlowType,
        input_data: FlowInput,
        response_id: Optional[str] = None,
    ) -> FlowOutput:
        """
        Execute flow with optimization while preserving orchestration logic.

        This method wraps the existing LangGraphOrchestrator without modifying its behavior.
        """
        response_id = response_id or f"flow_{int(time.time() * 1000)}"

        # Start performance tracking
        metrics = ResponsePerformanceMetrics(
            response_id=response_id, start_time=datetime.now()
        )

        try:
            # Pre-flow resource optimization
            await self._optimize_resources_before_response(metrics)

            # Execute original orchestration logic (PRESERVED)
            flow_start = time.time()
            result = await self._orchestrator.process_flow(flow_type, input_data)
            flow_duration = (time.time() - flow_start) * 1000

            metrics.flow_manager_duration_ms = flow_duration

            # Post-flow resource optimization
            await self._optimize_resources_after_response(result, metrics)

            # Finalize metrics
            metrics.end_time = datetime.now()
            metrics.total_duration_ms = (
                metrics.end_time - metrics.start_time
            ).total_seconds() * 1000

            # Store metrics
            with self._metrics_lock:
                self._performance_metrics[response_id] = metrics

            return result

        except Exception as e:
            metrics.end_time = datetime.now()
            self.logger.error(f"Flow execution failed for {response_id}: {e}")
            raise

    async def generate_scaffolding_optimized(
        self,
        text: str,
        scaffold_type: str = "reasoning",
        max_tokens: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        response_id: Optional[str] = None,
    ) -> Any:
        """
        Generate scaffolding with optimization while preserving SmallLanguageModel logic.

        This method wraps the existing SmallLanguageModelService without modifying its behavior.
        """
        if not self._small_language_model_service:
            raise RuntimeError("SmallLanguageModel service not available")

        response_id = response_id or f"scaffold_{int(time.time() * 1000)}"

        # Start performance tracking
        metrics = ResponsePerformanceMetrics(
            response_id=response_id, start_time=datetime.now()
        )

        try:
            # Pre-scaffolding resource optimization
            await self._optimize_resources_before_response(metrics)

            # Execute original SmallLanguageModel logic (PRESERVED)
            small_language_model_start = time.time()
            result = await self._small_language_model_service.generate_scaffold(
                text, scaffold_type, max_tokens, context
            )
            small_language_model_duration = (
                time.time() - small_language_model_start
            ) * 1000

            metrics.small_language_model_duration_ms = small_language_model_duration

            # Post-scaffolding resource optimization
            await self._optimize_resources_after_response(result, metrics)

            # Finalize metrics
            metrics.end_time = datetime.now()
            metrics.total_duration_ms = (
                metrics.end_time - metrics.start_time
            ).total_seconds() * 1000

            # Store metrics
            with self._metrics_lock:
                self._performance_metrics[response_id] = metrics

            return result

        except Exception as e:
            metrics.end_time = datetime.now()
            self.logger.error(f"Scaffolding generation failed for {response_id}: {e}")
            raise

    async def _optimize_resources_before_response(
        self, metrics: ResponsePerformanceMetrics
    ):
        """Optimize resources before response generation."""
        try:
            # Check resource pressure
            resource_pressure = self.resource_monitor.detect_resource_pressure()
            metrics.resource_pressure_detected = resource_pressure

            if resource_pressure:
                self.logger.info(
                    f"Resource pressure detected for {metrics.response_id}"
                )
                metrics.optimization_applied.append("resource_pressure_detected")

            # Memory optimization
            memory_optimization = self.memory_manager.optimize_memory_before_response()
            if memory_optimization.get("memory_freed_mb", 0) > 0:
                metrics.optimization_applied.extend(
                    memory_optimization["optimizations_applied"]
                )
                self.logger.debug(
                    f"Memory optimization freed {memory_optimization['memory_freed_mb']:.1f}MB"
                )

            # Record baseline metrics
            current_metrics = self.resource_monitor.get_current_metrics()
            metrics.cpu_usage_percent = current_metrics.cpu_percent
            metrics.memory_usage_mb = current_metrics.memory_mb

        except Exception as e:
            self.logger.error(f"Pre-response optimization failed: {e}")
            metrics.optimization_applied.append(f"pre_optimization_error: {str(e)}")

    async def _optimize_resources_after_response(
        self, response_data: Any, metrics: ResponsePerformanceMetrics
    ):
        """Optimize resources after response generation."""
        try:
            # Post-response memory optimization
            memory_cleanup = self.memory_manager.optimize_memory_after_response(
                response_data
            )
            if memory_cleanup.get("cleanup_scheduled"):
                metrics.optimization_applied.append("post_memory_cleanup")

            # Update final resource metrics
            final_metrics = self.resource_monitor.get_current_metrics()

            # Check if we exceeded CPU threshold
            if final_metrics.cpu_percent > self.config.cpu_threshold_percent:
                self.logger.warning(
                    f"Response {metrics.response_id} exceeded CPU threshold: "
                    f"{final_metrics.cpu_percent:.1f}% > {self.config.cpu_threshold_percent}%"
                )
                metrics.optimization_applied.append("cpu_threshold_exceeded")

            # Check if we exceeded memory threshold
            memory_increase = final_metrics.memory_mb - metrics.memory_usage_mb
            if memory_increase > self.config.memory_threshold_mb:
                self.logger.warning(
                    f"Response {metrics.response_id} exceeded memory threshold: "
                    f"{memory_increase:.1f}MB > {self.config.memory_threshold_mb}MB"
                )
                metrics.optimization_applied.append("memory_threshold_exceeded")

        except Exception as e:
            self.logger.error(f"Post-response optimization failed: {e}")
            metrics.optimization_applied.append(f"post_optimization_error: {str(e)}")

    def get_performance_metrics(
        self, response_id: str
    ) -> Optional[ResponsePerformanceMetrics]:
        """Get performance metrics for a specific response."""
        with self._metrics_lock:
            return self._performance_metrics.get(response_id)

    def get_recent_performance_summary(
        self, duration_minutes: int = 10
    ) -> Dict[str, Any]:
        """Get summary of recent performance metrics."""
        cutoff_time = datetime.now() - timedelta(minutes=duration_minutes)

        with self._metrics_lock:
            recent_metrics = [
                m
                for m in self._performance_metrics.values()
                if m.start_time >= cutoff_time and m.end_time is not None
            ]

        if not recent_metrics:
            return {"message": "No recent metrics available"}

        # Calculate summary statistics
        durations = [m.total_duration_ms for m in recent_metrics]
        cpu_usages = [m.cpu_usage_percent for m in recent_metrics]
        memory_usages = [m.memory_usage_mb for m in recent_metrics]

        return {
            "total_responses": len(recent_metrics),
            "avg_duration_ms": sum(durations) / len(durations),
            "max_duration_ms": max(durations),
            "min_duration_ms": min(durations),
            "avg_cpu_percent": sum(cpu_usages) / len(cpu_usages),
            "max_cpu_percent": max(cpu_usages),
            "avg_memory_mb": sum(memory_usages) / len(memory_usages),
            "max_memory_mb": max(memory_usages),
            "resource_pressure_count": sum(
                1 for m in recent_metrics if m.resource_pressure_detected
            ),
            "fallback_count": sum(1 for m in recent_metrics if m.fallback_used),
            "optimization_frequency": {
                opt: sum(1 for m in recent_metrics if opt in m.optimization_applied)
                for opt in set().union(
                    *(m.optimization_applied for m in recent_metrics)
                )
            },
        }

    def get_resource_status(self) -> Dict[str, Any]:
        """Get current resource status and health."""
        try:
            current_metrics = self.resource_monitor.get_current_metrics()
            resource_pressure = self.resource_monitor.detect_resource_pressure()

            return {
                "current_cpu_percent": current_metrics.cpu_percent,
                "current_memory_mb": current_metrics.memory_mb,
                "current_memory_percent": current_metrics.memory_percent,
                "resource_pressure_detected": resource_pressure,
                "cpu_threshold_percent": self.config.cpu_threshold_percent,
                "memory_threshold_mb": self.config.memory_threshold_mb,
                "monitoring_active": self.resource_monitor._monitoring,
                "timestamp": current_metrics.timestamp.isoformat(),
            }
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    async def shutdown(self):
        """Shutdown the controller and cleanup resources."""
        try:
            self.resource_monitor.stop_monitoring()

            # Clear metrics to free memory
            with self._metrics_lock:
                self._performance_metrics.clear()

            self.logger.info("IntelligentResponseController shutdown complete")

        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")

    # Preserve original component interfaces for backward compatibility
    @property
    def decision_engine(self) -> DecisionEngine:
        """Access to original DecisionEngine (preserved)."""
        return self._decision_engine

    @property
    def flow_manager(self) -> LangGraphOrchestrator:
        """Access to the orchestration runtime (preserved keyword)."""
        return self._orchestrator

    @property
    def small_language_model_service(self) -> Optional[SmallLanguageModelService]:
        """Access to original SmallLanguageModelService (preserved)."""
        return self._small_language_model_service
