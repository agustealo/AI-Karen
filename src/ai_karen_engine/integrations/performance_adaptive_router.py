"""
Performance Adaptive Routing System for Karen AI Intelligent Fallback

This module provides comprehensive performance monitoring and adaptive routing that optimizes
system performance based on real-time metrics, usage patterns, and provider capabilities.

Features:
- Real-time performance monitoring with comprehensive metrics tracking
- Adaptive routing algorithms with machine learning capabilities
- Performance-based optimization with automatic tuning
- Comprehensive analytics and reporting system
- Integration with all existing intelligent fallback system components
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import json
import statistics
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Callable, Union, Awaitable
from collections import defaultdict, deque
import weakref

from .intelligent_provider_registry import (
    IntelligentProviderRegistry, ProviderType, ProviderPriority,
    get_intelligent_provider_registry
)
from .capability_aware_selector import (
    SelectionCriteria, SelectionStrategy, RequestContext, get_capability_selector
)
from .model_availability_cache import get_model_availability_cache
from .intelligent_provider_switcher import (
    IntelligentProviderSwitcher, SwitchStrategy, SwitchTrigger,
    get_intelligent_provider_switcher
)
from ..monitoring.network_connectivity import NetworkStatus, get_network_monitor
from ..monitoring.comprehensive_health_monitor import (
    HealthStatus, HealthCheckType, get_comprehensive_health_monitor
)
from ..monitoring.health_based_decision_maker import (
    DecisionStrategy, get_health_decision_maker
)


class _FallbackChainManagerStub:
    """Stub replacing retired integrations/fallback_chain_manager.py."""

    def register_switch_callback(self, callback: Any) -> None:
        pass


def _get_fallback_chain_manager_stub() -> _FallbackChainManagerStub:
    return _FallbackChainManagerStub()

logger = logging.getLogger(__name__)


class AdaptiveStrategy(Enum):
    """Adaptive routing strategies."""
    LATENCY_OPTIMIZED = "latency_optimized"
    COST_OPTIMIZED = "cost_optimized"
    QUALITY_OPTIMIZED = "quality_optimized"
    BALANCED = "balanced"
    PREDICTIVE = "predictive"


class PerformanceMetricType(Enum):
    """Types of performance metrics."""
    LATENCY = auto()
    THROUGHPUT = auto()
    ERROR_RATE = auto()
    RESOURCE_UTILIZATION = auto()
    USER_SATISFACTION = auto()
    COST_EFFICIENCY = auto()
    RELIABILITY = auto()
    AVAILABILITY = auto()


class OptimizationObjective(Enum):
    """Performance optimization objectives."""
    MINIMIZE_LATENCY = auto()
    MAXIMIZE_THROUGHPUT = auto()
    MINIMIZE_COST = auto()
    MAXIMIZE_QUALITY = auto()
    MAXIMIZE_RELIABILITY = auto()
    BALANCE_ALL = auto()


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for a provider."""
    provider_name: str
    timestamp: float = field(default_factory=time.time)
    
    # Latency metrics
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_mean: float = 0.0
    latency_std: float = 0.0
    
    # Throughput metrics
    requests_per_second: float = 0.0
    tokens_per_second: float = 0.0
    concurrent_requests: int = 0
    
    # Error metrics
    error_rate: float = 0.0
    timeout_rate: float = 0.0
    retry_rate: float = 0.0
    
    # Resource utilization
    cpu_utilization: float = 0.0
    memory_utilization: float = 0.0
    network_bandwidth: float = 0.0
    
    # Quality metrics
    user_satisfaction_score: float = 0.0
    response_quality_score: float = 0.0
    capability_match_score: float = 0.0
    
    # Cost metrics
    cost_per_request: float = 0.0
    cost_per_token: float = 0.0
    cost_efficiency_score: float = 0.0
    
    # Reliability metrics
    uptime_percentage: float = 0.0
    success_rate: float = 0.0
    mean_time_to_recovery: float = 0.0
    
    # Custom metrics
    custom_metrics: Dict[str, float] = field(default_factory=dict)
    
    # Trend data
    latency_trend: str = "stable"  # improving, degrading, stable
    performance_trend: str = "stable"
    reliability_trend: str = "stable"


@dataclass
class PerformanceThreshold:
    """Thresholds for triggering routing changes."""
    metric_type: PerformanceMetricType
    warning_threshold: float
    critical_threshold: float
    trend_sensitivity: float = 0.1
    enabled: bool = True
    cooldown_period: float = 60.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingDecision:
    """Routing decision with rationale and metadata."""
    request_id: str
    context: str
    selected_provider: str
    strategy: AdaptiveStrategy
    confidence: float
    rationale: str
    alternatives: List[str] = field(default_factory=list)
    expected_performance: Dict[str, float] = field(default_factory=dict)
    risk_assessment: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingAnalytics:
    """Analytics for routing effectiveness."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    # Performance metrics
    average_latency: float = 0.0
    latency_distribution: Dict[str, float] = field(default_factory=dict)
    throughput_metrics: Dict[str, float] = field(default_factory=dict)
    
    # Provider usage
    provider_usage_counts: Dict[str, int] = field(default_factory=dict)
    provider_success_rates: Dict[str, float] = field(default_factory=dict)
    provider_performance_scores: Dict[str, float] = field(default_factory=dict)
    
    # Strategy effectiveness
    strategy_usage: Dict[str, int] = field(default_factory=dict)
    strategy_effectiveness: Dict[str, float] = field(default_factory=dict)
    
    # Routing quality
    routing_accuracy: float = 0.0
    user_satisfaction_average: float = 0.0
    cost_efficiency_score: float = 0.0
    
    # Anomaly detection
    anomalies_detected: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    
    # Optimization impact
    optimization_suggestions: List[str] = field(default_factory=list)
    performance_improvements: Dict[str, float] = field(default_factory=dict)
    
    last_updated: float = field(default_factory=time.time)


@dataclass
class AdaptiveConfig:
    """Configuration for adaptive routing system."""
    # Core settings
    enable_adaptive_routing: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_ADAPTIVE_ROUTING', 'true').lower() == 'true')
    enable_predictive_routing: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_PREDICTIVE_ROUTING', 'true').lower() == 'true')
    enable_ml_optimization: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_ML_OPTIMIZATION', 'true').lower() == 'true')
    
    # Performance monitoring
    metrics_collection_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_METRICS_INTERVAL', '5.0')))
    performance_history_size: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_PERFORMANCE_HISTORY_SIZE', '1000')))
    anomaly_detection_enabled: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ANOMALY_DETECTION', 'true').lower() == 'true')
    anomaly_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_ANOMALY_THRESHOLD', '2.0')))
    
    # Adaptive routing
    routing_update_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_ROUTING_UPDATE_INTERVAL', '30.0')))
    strategy_switch_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_STRATEGY_SWITCH_THRESHOLD', '0.2')))
    load_balancing_enabled: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_LOAD_BALANCING', 'true').lower() == 'true')
    max_concurrent_routes: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_MAX_CONCURRENT_ROUTES', '10')))
    
    # Machine learning
    ml_model_update_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_ML_UPDATE_INTERVAL', '300.0')))
    prediction_confidence_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_PREDICTION_CONFIDENCE', '0.7')))
    min_training_samples: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_MIN_TRAINING_SAMPLES', '100')))
    
    # Optimization
    auto_optimization_enabled: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_AUTO_OPTIMIZATION', 'true').lower() == 'true')
    optimization_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_OPTIMIZATION_INTERVAL', '600.0')))
    performance_degradation_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_PERFORMANCE_DEGRADATION_THRESHOLD', '0.15')))
    
    # Analytics and reporting
    analytics_history_size: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_ANALYTICS_HISTORY_SIZE', '5000')))
    enable_performance_dashboard: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_PERFORMANCE_DASHBOARD', 'true').lower() == 'true')
    report_generation_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_REPORT_INTERVAL', '3600.0')))
    
    # Integration settings
    integrate_with_fallback_manager: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_INTEGRATE_FALLBACK', 'true').lower() == 'true')
    integrate_with_health_monitor: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_INTEGRATE_HEALTH', 'true').lower() == 'true')
    integrate_with_provider_switcher: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_INTEGRATE_SWITCHER', 'true').lower() == 'true')


class PerformanceAdaptiveRouter:
    """
    Comprehensive performance monitoring and adaptive routing system.
    
    This system provides:
    - Real-time performance monitoring with comprehensive metrics
    - Adaptive routing algorithms with machine learning
    - Performance-based optimization with automatic tuning
    - Comprehensive analytics and reporting
    - Integration with all existing fallback system components
    """
    
    def __init__(self, config: Optional[AdaptiveConfig] = None):
        """Initialize performance adaptive router."""
        self.config = config or AdaptiveConfig()
        
        # Core state
        self._current_strategy = AdaptiveStrategy.BALANCED
        self._routing_decisions: deque = deque(maxlen=self.config.analytics_history_size)
        self._performance_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.config.performance_history_size))
        self._provider_metrics: Dict[str, PerformanceMetrics] = {}
        self._performance_thresholds: List[PerformanceThreshold] = []
        self._lock = threading.RLock()
        
        # Component integrations
        self._provider_registry = get_intelligent_provider_registry()
        self._capability_selector = get_capability_selector()
        self._model_cache = get_model_availability_cache()
        self._fallback_manager = _get_fallback_chain_manager_stub()
        self._network_monitor = get_network_monitor()
        self._health_monitor = get_comprehensive_health_monitor()
        self._decision_maker = get_health_decision_maker()
        self._provider_switcher = get_intelligent_provider_switcher()
        
        # Analytics and optimization
        self._analytics = RoutingAnalytics()
        self._routing_callbacks: List[Callable[[RoutingDecision], None]] = []
        self._performance_callbacks: List[Callable[[PerformanceMetrics], None]] = []
        
        # Machine learning components
        self._ml_models: Dict[str, Any] = {}
        self._training_data: List[Dict[str, Any]] = []
        self._prediction_cache: Dict[str, Tuple[float, float]] = {}  # prediction, confidence
        
        # Background tasks
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._optimization_task: Optional[asyncio.Task] = None
        self._ml_training_task: Optional[asyncio.Task] = None
        self._reporting_task: Optional[asyncio.Task] = None
        
        # Load balancing
        self._load_balancer_state: Dict[str, Dict[str, Any]] = {}
        self._routing_semaphore = asyncio.Semaphore(self.config.max_concurrent_routes)
        
        # Setup default thresholds
        self._setup_default_thresholds()
        
        logger.info("Performance adaptive router initialized")
    
    async def start_monitoring(self) -> None:
        """Start performance monitoring and adaptive routing."""
        if self._monitoring_active:
            logger.warning("Performance adaptive router monitoring already active")
            return
        
        self._monitoring_active = True
        
        # Start monitoring task
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Start optimization task
        if self.config.auto_optimization_enabled:
            self._optimization_task = asyncio.create_task(self._optimization_loop())
        
        # Start ML training task
        if self.config.enable_ml_optimization:
            self._ml_training_task = asyncio.create_task(self._ml_training_loop())
        
        # Start reporting task
        if self.config.enable_performance_dashboard:
            self._reporting_task = asyncio.create_task(self._reporting_loop())
        
        # Register callbacks with integrated components
        await self._setup_integrations()
        
        logger.info("Performance adaptive router monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop performance monitoring and adaptive routing."""
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        
        # Cancel background tasks
        tasks = [self._monitoring_task, self._optimization_task, 
                 self._ml_training_task, self._reporting_task]
        
        for task in tasks:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("Performance adaptive router monitoring stopped")
    
    def register_routing_callback(self, callback: Callable[[RoutingDecision], None]) -> None:
        """Register callback for routing decisions."""
        self._routing_callbacks.append(callback)
    
    def register_performance_callback(self, callback: Callable[[PerformanceMetrics], None]) -> None:
        """Register callback for performance updates."""
        self._performance_callbacks.append(callback)
    
    async def route_request(
        self,
        request_id: str,
        context: str,
        requirements: Optional[Dict[str, Any]] = None,
        strategy: Optional[AdaptiveStrategy] = None
    ) -> RoutingDecision:
        """
        Route a request using adaptive routing algorithm.
        
        Args:
            request_id: Unique identifier for the request
            context: Request context (e.g., 'chat', 'code', 'embedding')
            requirements: Additional requirements and constraints
            strategy: Routing strategy to use (None for auto-selection)
            
        Returns:
            RoutingDecision with selected provider and rationale
        """
        async with self._routing_semaphore:
            start_time = time.time()
            
            try:
                # Determine routing strategy
                if strategy:
                    routing_strategy = strategy
                else:
                    routing_strategy = await self._select_optimal_strategy(context, requirements)
                
                # Get candidate providers
                candidates = await self._get_candidate_providers(context, requirements)
                
                if not candidates:
                    # Fallback to any available provider
                    candidates = await self._get_fallback_providers(context)
                
                if not candidates:
                    raise Exception("No suitable providers available")
                
                # Select optimal provider using strategy
                selected_provider, confidence, rationale = await self._select_provider(
                    candidates, routing_strategy, context, requirements
                )
                
                # Create routing decision
                decision = RoutingDecision(
                    request_id=request_id,
                    context=context,
                    selected_provider=selected_provider,
                    strategy=routing_strategy,
                    confidence=confidence,
                    rationale=rationale,
                    alternatives=[p for p in candidates if p != selected_provider],
                    expected_performance=await self._predict_performance(selected_provider, context),
                    risk_assessment=await self._assess_risks(selected_provider, context),
                    metadata={
                        'routing_time': time.time() - start_time,
                        'candidates_count': len(candidates),
                        'requirements': requirements or {}
                    }
                )
                
                # Record decision
                self._record_routing_decision(decision)
                
                # Trigger callbacks
                for callback in self._routing_callbacks:
                    try:
                        callback(decision)
                    except Exception as e:
                        logger.error(f"Routing callback error: {e}")
                
                # Update load balancer state
                self._update_load_balancer_state(selected_provider, context)
                
                logger.info(
                    f"Routed request {request_id} to {selected_provider} "
                    f"(strategy: {routing_strategy.value}, confidence: {confidence:.3f})"
                )
                
                return decision
                
            except Exception as e:
                logger.error(f"Routing failed for request {request_id}: {e}")
                
                # Create fallback decision
                return RoutingDecision(
                    request_id=request_id,
                    context=context,
                    selected_provider="fallback",
                    strategy=strategy or AdaptiveStrategy.BALANCED,
                    confidence=0.0,
                    rationale=f"Routing failed: {str(e)}",
                    metadata={
                        'routing_time': time.time() - start_time,
                        'error': str(e)
                    }
                )
    
    async def record_performance(
        self,
        provider_name: str,
        metrics: Dict[str, Any]
    ) -> None:
        """
        Record performance metrics for a provider.
        
        Args:
            provider_name: Name of the provider
            metrics: Performance metrics dictionary
        """
        try:
            # Create performance metrics object
            performance_metrics = PerformanceMetrics(
                provider_name=provider_name,
                **metrics
            )
            
            # Update provider metrics
            with self._lock:
                self._provider_metrics[provider_name] = performance_metrics
                
                # Add to history
                self._performance_history[provider_name].append(performance_metrics)
            
            # Check thresholds and trigger alerts
            await self._check_performance_thresholds(performance_metrics)
            
            # Detect anomalies
            if self.config.anomaly_detection_enabled:
                await self._detect_performance_anomalies(performance_metrics)
            
            # Update ML models
            if self.config.enable_ml_optimization:
                await self._update_ml_models(provider_name, performance_metrics)
            
            # Trigger callbacks
            for callback in self._performance_callbacks:
                try:
                    callback(performance_metrics)
                except Exception as e:
                    logger.error(f"Performance callback error: {e}")
            
            # Update integrated components
            await self._update_integrated_components(provider_name, performance_metrics)
            
        except Exception as e:
            logger.error(f"Failed to record performance for {provider_name}: {e}")
    
    def get_provider_performance(self, provider_name: str) -> Optional[PerformanceMetrics]:
        """Get current performance metrics for a provider."""
        with self._lock:
            return self._provider_metrics.get(provider_name)
    
    def get_all_provider_performance(self) -> Dict[str, PerformanceMetrics]:
        """Get performance metrics for all providers."""
        with self._lock:
            return self._provider_metrics.copy()
    
    def get_routing_analytics(self) -> RoutingAnalytics:
        """Get comprehensive routing analytics."""
        with self._lock:
            return self._analytics
    
    def get_performance_trends(
        self,
        provider_name: str,
        window_minutes: int = 60
    ) -> Dict[str, Any]:
        """Get performance trends for a provider."""
        with self._lock:
            history = self._performance_history.get(provider_name, deque())
            
            # Filter by time window
            cutoff_time = time.time() - (window_minutes * 60)
            recent_metrics = [m for m in history if m.timestamp >= cutoff_time]
            
            if not recent_metrics:
                return {}
            
            # Calculate trends
            latency_trend = self._calculate_trend([m.latency_mean for m in recent_metrics])
            throughput_trend = self._calculate_trend([m.requests_per_second for m in recent_metrics])
            error_rate_trend = self._calculate_trend([m.error_rate for m in recent_metrics])
            
            return {
                'provider': provider_name,
                'window_minutes': window_minutes,
                'sample_count': len(recent_metrics),
                'latency_trend': latency_trend,
                'throughput_trend': throughput_trend,
                'error_rate_trend': error_rate_trend,
                'overall_trend': self._calculate_overall_trend([
                    latency_trend, throughput_trend, error_rate_trend
                ])
            }
    
    async def optimize_routing(self, objectives: List[OptimizationObjective]) -> Dict[str, Any]:
        """
        Optimize routing based on specified objectives.
        
        Args:
            objectives: List of optimization objectives
            
        Returns:
            Optimization results and recommendations
        """
        try:
            optimization_start = time.time()
            
            # Analyze current performance
            current_performance = await self._analyze_current_performance()
            
            # Generate optimization recommendations
            recommendations = await self._generate_optimization_recommendations(
                current_performance, objectives
            )
            
            # Apply optimizations if auto-optimization is enabled
            applied_optimizations = []
            if self.config.auto_optimization_enabled:
                applied_optimizations = await self._apply_optimizations(recommendations)
            
            optimization_time = time.time() - optimization_start
            
            result = {
                'objectives': [obj.name for obj in objectives],
                'current_performance': current_performance,
                'recommendations': recommendations,
                'applied_optimizations': applied_optimizations,
                'optimization_time': optimization_time,
                'timestamp': time.time()
            }
            
            logger.info(f"Routing optimization completed in {optimization_time:.3f}s")
            
            return result
            
        except Exception as e:
            logger.error(f"Routing optimization failed: {e}")
            return {
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _setup_default_thresholds(self) -> None:
        """Setup default performance thresholds."""
        default_thresholds = [
            PerformanceThreshold(
                metric_type=PerformanceMetricType.LATENCY,
                warning_threshold=2.0,
                critical_threshold=5.0,
                trend_sensitivity=0.2
            ),
            PerformanceThreshold(
                metric_type=PerformanceMetricType.ERROR_RATE,
                warning_threshold=0.05,
                critical_threshold=0.15,
                trend_sensitivity=0.1
            ),
            PerformanceThreshold(
                metric_type=PerformanceMetricType.THROUGHPUT,
                warning_threshold=10.0,
                critical_threshold=5.0,
                trend_sensitivity=0.15
            ),
            PerformanceThreshold(
                metric_type=PerformanceMetricType.RESOURCE_UTILIZATION,
                warning_threshold=0.8,
                critical_threshold=0.95,
                trend_sensitivity=0.1
            ),
            PerformanceThreshold(
                metric_type=PerformanceMetricType.USER_SATISFACTION,
                warning_threshold=0.7,
                critical_threshold=0.5,
                trend_sensitivity=0.15
            )
        ]
        
        self._performance_thresholds.extend(default_thresholds)
    
    async def _setup_integrations(self) -> None:
        """Setup integrations with other system components."""
        try:
            # Register with provider registry
            if self.config.integrate_with_fallback_manager:
                self._fallback_manager.register_switch_callback(
                    self._on_fallback_switch
                )
            
            # Register with health monitor
            if self.config.integrate_with_health_monitor:
                self._health_monitor.register_alert_callback(
                    self._on_health_alert
                )
            
            # Register with provider switcher
            if self.config.integrate_with_provider_switcher:
                self._provider_switcher.register_switch_callback(
                    self._on_provider_switch
                )
            
            logger.info("Component integrations setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup integrations: {e}")
    
    async def _monitoring_loop(self) -> None:
        """Main performance monitoring loop."""
        logger.info("Performance monitoring loop started")
        
        while self._monitoring_active:
            try:
                # Collect performance metrics from all providers
                await self._collect_performance_metrics()
                
                # Update analytics
                await self._update_analytics()
                
                # Check for performance degradation
                await self._check_performance_degradation()
                
                # Sleep until next collection
                await asyncio.sleep(self.config.metrics_collection_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)
        
        logger.info("Performance monitoring loop stopped")
    
    async def _collect_performance_metrics(self) -> None:
        """Collect performance metrics from all providers."""
        try:
            # Get all registered providers
            all_providers = self._provider_registry._registrations
            
            for provider_name, provider_reg in all_providers.items():
                # Collect basic metrics from provider registry
                registry_metrics = self._provider_registry.get_provider_metrics(provider_name)
                
                if registry_metrics:
                    # Convert to performance metrics format
                    metrics = {
                        'latency_mean': registry_metrics.average_latency,
                        'success_rate': registry_metrics.success_rate,
                        'error_rate': 1.0 - registry_metrics.success_rate,
                        'requests_per_second': self._calculate_rps(provider_name),
                        'cost_per_request': registry_metrics.cost_per_request
                    }
                    
                    # Add health monitor metrics
                    if self.config.integrate_with_health_monitor:
                        health_result = self._health_monitor.get_component_health(provider_name)
                        if health_result:
                            metrics.update({
                                'uptime_percentage': health_result.score * 100,
                                'reliability_score': health_result.score
                            })
                    
                    # Record performance
                    await self.record_performance(provider_name, metrics)
                
        except Exception as e:
            logger.error(f"Failed to collect performance metrics: {e}")
    
    def _calculate_rps(self, provider_name: str) -> float:
        """Calculate requests per second for a provider."""
        with self._lock:
            history = self._performance_history.get(provider_name, deque())
            if len(history) < 2:
                return 0.0
            
            # Calculate RPS from recent history
            recent_metrics = list(history)[-10:]  # Last 10 samples
            if len(recent_metrics) < 2:
                return 0.0
            
            time_span = recent_metrics[-1].timestamp - recent_metrics[0].timestamp
            if time_span <= 0:
                return 0.0
            
            return len(recent_metrics) / time_span
    
    async def _update_analytics(self) -> None:
        """Update routing analytics."""
        try:
            with self._lock:
                # Update basic counts
                self._analytics.total_requests = len(self._routing_decisions)
                self._analytics.successful_requests = sum(
                    1 for d in self._routing_decisions 
                    if d.selected_provider != "fallback"
                )
                self._analytics.failed_requests = (
                    self._analytics.total_requests - self._analytics.successful_requests
                )
                
                # Update provider usage
                provider_usage = defaultdict(int)
                strategy_usage = defaultdict(int)
                
                for decision in self._routing_decisions:
                    provider_usage[decision.selected_provider] += 1
                    strategy_usage[decision.strategy.value] += 1
                
                self._analytics.provider_usage_counts = dict(provider_usage)
                self._analytics.strategy_usage = dict(strategy_usage)
                
                # Calculate success rates
                total_requests = max(self._analytics.total_requests, 1)
                self._analytics.routing_accuracy = (
                    self._analytics.successful_requests / total_requests
                )
                
                # Update provider success rates
                for provider_name in provider_usage:
                    provider_decisions = [
                        d for d in self._routing_decisions 
                        if d.selected_provider == provider_name
                    ]
                    if provider_decisions:
                        success_count = sum(
                            1 for d in provider_decisions 
                            if d.selected_provider != "fallback"
                        )
                        self._analytics.provider_success_rates[provider_name] = (
                            success_count / len(provider_decisions)
                        )
                
                self._analytics.last_updated = time.time()
                
        except Exception as e:
            logger.error(f"Failed to update analytics: {e}")
    
    async def _check_performance_degradation(self) -> None:
        """Check for performance degradation across providers."""
        try:
            with self._lock:
                for provider_name, metrics in self._provider_metrics.items():
                    # Check against thresholds
                    for threshold in self._performance_thresholds:
                        if not threshold.enabled:
                            continue
                        
                        current_value = self._get_metric_value(metrics, threshold.metric_type)
                        if current_value is None:
                            continue
                        
                        # Check if threshold is exceeded
                        if current_value >= threshold.critical_threshold:
                            logger.critical(
                                f"Critical performance threshold exceeded for {provider_name}: "
                                f"{threshold.metric_type.name} = {current_value:.3f} "
                                f"(threshold: {threshold.critical_threshold:.3f})"
                            )
                            
                            # Trigger emergency routing adjustment
                            await self._handle_performance_crisis(provider_name, threshold)
                        
                        elif current_value >= threshold.warning_threshold:
                            logger.warning(
                                f"Warning threshold exceeded for {provider_name}: "
                                f"{threshold.metric_type.name} = {current_value:.3f} "
                                f"(threshold: {threshold.warning_threshold:.3f})"
                            )
                
        except Exception as e:
            logger.error(f"Failed to check performance degradation: {e}")
    
    def _get_metric_value(self, metrics: PerformanceMetrics, metric_type: PerformanceMetricType) -> Optional[float]:
        """Get value for a specific metric type."""
        mapping = {
            PerformanceMetricType.LATENCY: metrics.latency_mean,
            PerformanceMetricType.ERROR_RATE: metrics.error_rate,
            PerformanceMetricType.THROUGHPUT: metrics.requests_per_second,
            PerformanceMetricType.RESOURCE_UTILIZATION: max(
                metrics.cpu_utilization, metrics.memory_utilization
            ),
            PerformanceMetricType.USER_SATISFACTION: metrics.user_satisfaction_score,
            PerformanceMetricType.COST_EFFICIENCY: metrics.cost_efficiency_score,
            PerformanceMetricType.RELIABILITY: metrics.success_rate,
            PerformanceMetricType.AVAILABILITY: metrics.uptime_percentage / 100.0
        }
        return mapping.get(metric_type)
    
    async def _handle_performance_crisis(self, provider_name: str, threshold: PerformanceThreshold) -> None:
        """Handle performance crisis for a provider."""
        try:
            # Immediately reduce provider priority
            provider_info = self._provider_registry.get_provider_info(provider_name)
            if provider_info:
                # Temporarily increase priority value (lower priority)
                original_priority = provider_info.priority
                provider_info.priority = ProviderPriority.EXPERIMENTAL
                
                # Schedule priority restoration
                asyncio.create_task(
                    self._restore_provider_priority(provider_name, original_priority, threshold.cooldown_period)
                )
            
            # Trigger immediate rerouting if provider switcher is available
            if self.config.integrate_with_provider_switcher:
                # Find contexts using this provider
                affected_contexts = [
                    context for context, provider in self._decision_maker._current_providers.items()
                    if provider == provider_name
                ]
                
                for context in affected_contexts:
                    await self._provider_switcher.switch_provider(
                        context=context,
                        strategy=SwitchStrategy.IMMEDIATE,
                        reason=f"Performance crisis: {threshold.metric_type.name}"
                    )
            
            logger.info(f"Handled performance crisis for {provider_name}")
            
        except Exception as e:
            logger.error(f"Failed to handle performance crisis for {provider_name}: {e}")
    
    async def _restore_provider_priority(
        self,
        provider_name: str,
        original_priority: ProviderPriority,
        delay: float
    ) -> None:
        """Restore provider priority after delay."""
        await asyncio.sleep(delay)
        
        try:
            provider_info = self._provider_registry.get_provider_info(provider_name)
            if provider_info:
                provider_info.priority = original_priority
                logger.info(f"Restored priority for {provider_name}")
        except Exception as e:
            logger.error(f"Failed to restore priority for {provider_name}: {e}")
    
    async def _select_optimal_strategy(
        self,
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> AdaptiveStrategy:
        """Select optimal routing strategy based on context and requirements."""
        try:
            # Get current network status
            network_status = self._network_monitor.get_current_status()
            
            # Get current system load
            system_load = self._calculate_system_load()
            
            # Base strategy selection
            if network_status == NetworkStatus.OFFLINE:
                return AdaptiveStrategy.BALANCED  # Prioritize balanced approach when offline
            elif system_load > 0.8:
                return AdaptiveStrategy.LATENCY_OPTIMIZED  # Prioritize speed under high load
            elif requirements and requirements.get('cost_sensitive', False):
                return AdaptiveStrategy.COST_OPTIMIZED
            elif requirements and requirements.get('quality_sensitive', False):
                return AdaptiveStrategy.QUALITY_OPTIMIZED
            elif self.config.enable_predictive_routing:
                # Use ML to predict best strategy
                predicted_strategy = await self._predict_optimal_strategy(context, requirements)
                if predicted_strategy:
                    return predicted_strategy
            
            return AdaptiveStrategy.BALANCED
            
        except Exception as e:
            logger.error(f"Failed to select optimal strategy: {e}")
            return AdaptiveStrategy.BALANCED
    
    def _calculate_system_load(self) -> float:
        """Calculate current system load."""
        try:
            with self._lock:
                if not self._provider_metrics:
                    return 0.0
                
                # Calculate average resource utilization
                total_cpu = sum(m.cpu_utilization for m in self._provider_metrics.values())
                total_memory = sum(m.memory_utilization for m in self._provider_metrics.values())
                
                provider_count = len(self._provider_metrics)
                avg_cpu = total_cpu / provider_count if provider_count > 0 else 0.0
                avg_memory = total_memory / provider_count if provider_count > 0 else 0.0
                
                return max(avg_cpu, avg_memory)
                
        except Exception as e:
            logger.error(f"Failed to calculate system load: {e}")
            return 0.5  # Default to medium load
    
    async def _get_candidate_providers(
        self,
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Get list of candidate providers for routing."""
        try:
            # Get all registered providers
            all_providers = self._provider_registry._registrations
            
            candidates = []
            
            for provider_name, provider_reg in all_providers.items():
                # Check basic availability
                if not self._is_provider_available(provider_name, provider_reg):
                    continue
                
                # Check capability requirements
                if requirements and 'capabilities' in requirements:
                    required_caps = set(requirements['capabilities'])
                    provider_caps = set()
                    for model in provider_reg.base_registration.models:
                        provider_caps.update(model.capabilities)
                    
                    if not required_caps.issubset(provider_caps):
                        continue
                
                # Check performance constraints
                if not self._meets_performance_constraints(provider_name, requirements):
                    continue
                
                candidates.append(provider_name)
            
            return candidates
            
        except Exception as e:
            logger.error(f"Failed to get candidate providers: {e}")
            return []
    
    def _is_provider_available(self, provider_name: str, provider_reg: Any) -> bool:
        """Check if a provider is available for routing."""
        try:
            # Check network dependency
            network_status = self._network_monitor.get_current_status()
            if provider_reg.network_dependent and network_status == NetworkStatus.OFFLINE:
                if not provider_reg.offline_capable:
                    return False
            
            # Check circuit breaker
            current_time = time.time()
            if current_time < provider_reg.metrics.circuit_breaker_until:
                return False
            
            # Check rate limiting
            if current_time < provider_reg.metrics.rate_limit_until:
                return False
            
            # Check health status
            if self.config.integrate_with_health_monitor:
                health_result = self._health_monitor.get_component_health(provider_name)
                if health_result and health_result.status == HealthStatus.UNHEALTHY:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check provider availability for {provider_name}: {e}")
            return False
    
    def _meets_performance_constraints(
        self,
        provider_name: str,
        requirements: Optional[Dict[str, Any]]
    ) -> bool:
        """Check if provider meets performance constraints."""
        if not requirements:
            return True
        
        try:
            metrics = self._provider_metrics.get(provider_name)
            if not metrics:
                return True  # No metrics, assume it meets constraints
            
            # Check latency constraint
            max_latency = requirements.get('max_latency')
            if max_latency and metrics.latency_mean > max_latency:
                return False
            
            # Check error rate constraint
            max_error_rate = requirements.get('max_error_rate')
            if max_error_rate and metrics.error_rate > max_error_rate:
                return False
            
            # Check cost constraint
            max_cost = requirements.get('max_cost')
            if max_cost and metrics.cost_per_request > max_cost:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check performance constraints for {provider_name}: {e}")
            return True
    
    async def _get_fallback_providers(self, context: str) -> List[str]:
        """Get fallback providers when no candidates are available."""
        try:
            # Get all providers as fallback
            all_providers = list(self._provider_registry._registrations.keys())
            
            # Prioritize local and offline-capable providers
            fallback_order = []
            
            for provider_name in all_providers:
                provider_reg = self._provider_registry._registrations[provider_name]
                
                if provider_reg.provider_type == ProviderType.LOCAL:
                    fallback_order.insert(0, provider_name)
                elif provider_reg.offline_capable:
                    fallback_order.append(provider_name)
                else:
                    fallback_order.append(provider_name)
            
            return fallback_order
            
        except Exception as e:
            logger.error(f"Failed to get fallback providers: {e}")
            return []
    
    async def _select_provider(
        self,
        candidates: List[str],
        strategy: AdaptiveStrategy,
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Select optimal provider from candidates using strategy."""
        try:
            if not candidates:
                return "fallback", 0.0, "No candidates available"
            
            if strategy == AdaptiveStrategy.LATENCY_OPTIMIZED:
                return await self._select_by_latency(candidates, context)
            elif strategy == AdaptiveStrategy.COST_OPTIMIZED:
                return await self._select_by_cost(candidates, context)
            elif strategy == AdaptiveStrategy.QUALITY_OPTIMIZED:
                return await self._select_by_quality(candidates, context)
            elif strategy == AdaptiveStrategy.PREDICTIVE:
                return await self._select_by_prediction(candidates, context, requirements)
            else:  # BALANCED
                return await self._select_balanced(candidates, context, requirements)
                
        except Exception as e:
            logger.error(f"Failed to select provider: {e}")
            return candidates[0] if candidates else "fallback", 0.0, f"Selection failed: {str(e)}"
    
    async def _select_by_latency(self, candidates: List[str], context: str) -> Tuple[str, float, str]:
        """Select provider with lowest latency."""
        best_provider = None
        best_latency = float('inf')
        
        for provider_name in candidates:
            metrics = self._provider_metrics.get(provider_name)
            if metrics and metrics.latency_mean > 0:
                if metrics.latency_mean < best_latency:
                    best_latency = metrics.latency_mean
                    best_provider = provider_name
        
        if best_provider:
            confidence = max(0.0, 1.0 - (best_latency / 5.0))  # Normalize to 0-1
            return best_provider, confidence, f"Lowest latency: {best_latency:.3f}s"
        
        # Fallback to first candidate
        return candidates[0], 0.5, "No latency data available"
    
    async def _select_by_cost(self, candidates: List[str], context: str) -> Tuple[str, float, str]:
        """Select provider with lowest cost."""
        best_provider = None
        best_cost = float('inf')
        
        for provider_name in candidates:
            metrics = self._provider_metrics.get(provider_name)
            if metrics and metrics.cost_per_request > 0:
                if metrics.cost_per_request < best_cost:
                    best_cost = metrics.cost_per_request
                    best_provider = provider_name
        
        if best_provider:
            confidence = max(0.0, 1.0 - (best_cost / 0.1))  # Normalize assuming max $0.1/request
            return best_provider, confidence, f"Lowest cost: ${best_cost:.6f}/request"
        
        # Fallback to first candidate
        return candidates[0], 0.5, "No cost data available"
    
    async def _select_by_quality(self, candidates: List[str], context: str) -> Tuple[str, float, str]:
        """Select provider with highest quality score."""
        best_provider = None
        best_quality = 0.0
        
        for provider_name in candidates:
            metrics = self._provider_metrics.get(provider_name)
            if metrics:
                # Combine quality metrics
                quality_score = (
                    metrics.user_satisfaction_score * 0.4 +
                    metrics.response_quality_score * 0.4 +
                    metrics.success_rate * 0.2
                )
                
                if quality_score > best_quality:
                    best_quality = quality_score
                    best_provider = provider_name
        
        if best_provider:
            return best_provider, best_quality, f"Highest quality score: {best_quality:.3f}"
        
        # Fallback to first candidate
        return candidates[0], 0.5, "No quality data available"
    
    async def _select_by_prediction(
        self,
        candidates: List[str],
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Select provider using ML prediction."""
        try:
            if not self.config.enable_ml_optimization:
                return await self._select_balanced(candidates, context, requirements)
            
            best_provider = None
            best_prediction = 0.0
            best_confidence = 0.0
            
            for provider_name in candidates:
                prediction, confidence = await self._predict_provider_performance(
                    provider_name, context, requirements
                )
                
                if confidence > self.config.prediction_confidence_threshold:
                    if prediction > best_prediction:
                        best_prediction = prediction
                        best_confidence = confidence
                        best_provider = provider_name
            
            if best_provider:
                return (
                    best_provider,
                    best_confidence,
                    f"ML prediction: {best_prediction:.3f} (confidence: {best_confidence:.3f})"
                )
            
            # Fallback to balanced selection
            return await self._select_balanced(candidates, context, requirements)
            
        except Exception as e:
            logger.error(f"Failed to select by prediction: {e}")
            return await self._select_balanced(candidates, context, requirements)
    
    async def _select_balanced(
        self,
        candidates: List[str],
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Select provider using balanced scoring."""
        best_provider = None
        best_score = 0.0
        score_breakdown = {}
        
        for provider_name in candidates:
            metrics = self._provider_metrics.get(provider_name)
            provider_reg = self._provider_registry._registrations.get(provider_name)
            
            if not metrics or not provider_reg:
                continue
            
            # Calculate balanced score
            score = 0.0
            
            # Latency score (30% weight)
            latency_score = max(0.0, 1.0 - (metrics.latency_mean / 5.0))
            score += latency_score * 0.3
            score_breakdown['latency'] = latency_score
            
            # Cost score (20% weight)
            cost_score = max(0.0, 1.0 - (metrics.cost_per_request / 0.1))
            score += cost_score * 0.2
            score_breakdown['cost'] = cost_score
            
            # Quality score (25% weight)
            quality_score = (
                metrics.user_satisfaction_score * 0.4 +
                metrics.response_quality_score * 0.4 +
                metrics.success_rate * 0.2
            )
            score += quality_score * 0.25
            score_breakdown['quality'] = quality_score
            
            # Reliability score (25% weight)
            reliability_score = metrics.success_rate
            score += reliability_score * 0.25
            score_breakdown['reliability'] = reliability_score
            
            if score > best_score:
                best_score = score
                best_provider = provider_name
        
        if best_provider:
            breakdown_str = ", ".join([f"{k}: {v:.3f}" for k, v in score_breakdown.items()])
            return best_provider, best_score, f"Balanced score: {best_score:.3f} ({breakdown_str})"
        
        # Fallback to first candidate
        return candidates[0], 0.5, "No performance data available"
    
    async def _predict_performance(
        self,
        provider_name: str,
        context: str
    ) -> Dict[str, float]:
        """Predict performance for a provider in a context."""
        try:
            metrics = self._provider_metrics.get(provider_name)
            if not metrics:
                return {}
            
            # Base predictions on current metrics
            predictions = {
                'expected_latency': metrics.latency_mean,
                'expected_throughput': metrics.requests_per_second,
                'expected_success_rate': metrics.success_rate,
                'expected_cost': metrics.cost_per_request,
                'expected_quality': metrics.response_quality_score
            }
            
            # Apply context adjustments
            context_multiplier = self._get_context_multiplier(context)
            for key in predictions:
                if key in ['expected_latency']:
                    predictions[key] *= context_multiplier
                elif key in ['expected_throughput', 'expected_success_rate', 'expected_quality']:
                    predictions[key] *= (2.0 - context_multiplier)  # Inverse for positive metrics
            
            return predictions
            
        except Exception as e:
            logger.error(f"Failed to predict performance for {provider_name}: {e}")
            return {}
    
    def _get_context_multiplier(self, context: str) -> float:
        """Get context-specific performance multiplier."""
        context_multipliers = {
            'realtime': 1.2,      # Higher latency expectation
            'batch': 0.8,          # Lower latency expectation
            'chat': 1.0,           # Normal expectation
            'code': 1.1,           # Slightly higher latency
            'embedding': 0.9,       # Lower latency expectation
            'analytics': 1.3,        # Higher latency expectation
        }
        return context_multipliers.get(context, 1.0)
    
    async def _assess_risks(self, provider_name: str, context: str) -> Dict[str, float]:
        """Assess risks for using a provider in a context."""
        try:
            metrics = self._provider_metrics.get(provider_name)
            if not metrics:
                return {'overall_risk': 0.5}  # Unknown risk
            
            risks = {}
            
            # Latency risk
            if metrics.latency_mean > 3.0:
                risks['latency_risk'] = min(1.0, metrics.latency_mean / 10.0)
            else:
                risks['latency_risk'] = 0.0
            
            # Error risk
            risks['error_risk'] = metrics.error_rate
            
            # Reliability risk
            risks['reliability_risk'] = 1.0 - metrics.success_rate
            
            # Cost risk
            if metrics.cost_per_request > 0.05:
                risks['cost_risk'] = min(1.0, metrics.cost_per_request / 0.1)
            else:
                risks['cost_risk'] = 0.0
            
            # Network dependency risk
            provider_reg = self._provider_registry._registrations.get(provider_name)
            if provider_reg and provider_reg.network_dependent:
                network_status = self._network_monitor.get_current_status()
                if network_status == NetworkStatus.OFFLINE:
                    risks['network_risk'] = 1.0
                elif network_status == NetworkStatus.DEGRADED:
                    risks['network_risk'] = 0.5
                else:
                    risks['network_risk'] = 0.1
            else:
                risks['network_risk'] = 0.0
            
            # Calculate overall risk
            overall_risk = sum(risks.values()) / len(risks)
            risks['overall_risk'] = overall_risk
            
            return risks
            
        except Exception as e:
            logger.error(f"Failed to assess risks for {provider_name}: {e}")
            return {'overall_risk': 0.5}
    
    def _record_routing_decision(self, decision: RoutingDecision) -> None:
        """Record a routing decision for analytics."""
        with self._lock:
            self._routing_decisions.append(decision)
            
            # Update analytics
            self._analytics.total_requests += 1
            
            if decision.selected_provider != "fallback":
                self._analytics.successful_requests += 1
            else:
                self._analytics.failed_requests += 1
    
    def _update_load_balancer_state(self, provider_name: str, context: str) -> None:
        """Update load balancer state for a provider."""
        with self._lock:
            if provider_name not in self._load_balancer_state:
                self._load_balancer_state[provider_name] = {
                    'request_count': 0,
                    'contexts': defaultdict(int),
                    'last_used': time.time()
                }
            
            state = self._load_balancer_state[provider_name]
            state['request_count'] += 1
            state['contexts'][context] += 1
            state['last_used'] = time.time()
    
    async def _check_performance_thresholds(self, metrics: PerformanceMetrics) -> None:
        """Check performance against configured thresholds."""
        try:
            for threshold in self._performance_thresholds:
                if not threshold.enabled:
                    continue
                
                current_value = self._get_metric_value(metrics, threshold.metric_type)
                if current_value is None:
                    continue
                
                # Check critical threshold
                if current_value >= threshold.critical_threshold:
                    logger.critical(
                        f"CRITICAL: {metrics.provider_name} {threshold.metric_type.name} "
                        f"= {current_value:.3f} (threshold: {threshold.critical_threshold:.3f})"
                    )
                
                # Check warning threshold
                elif current_value >= threshold.warning_threshold:
                    logger.warning(
                        f"WARNING: {metrics.provider_name} {threshold.metric_type.name} "
                        f"= {current_value:.3f} (threshold: {threshold.warning_threshold:.3f})"
                    )
                
        except Exception as e:
            logger.error(f"Failed to check performance thresholds: {e}")
    
    async def _detect_performance_anomalies(self, metrics: PerformanceMetrics) -> None:
        """Detect performance anomalies using statistical analysis."""
        try:
            provider_name = metrics.provider_name
            history = self._performance_history.get(provider_name, deque())
            
            if len(history) < 10:  # Need sufficient history
                return
            
            # Get recent metrics for comparison
            recent_metrics = list(history)[-10:]
            
            # Calculate statistical bounds
            latency_values = [m.latency_mean for m in recent_metrics]
            error_rates = [m.error_rate for m in recent_metrics]
            
            latency_mean = statistics.mean(latency_values)
            latency_std = statistics.stdev(latency_values) if len(latency_values) > 1 else 0.0
            error_mean = statistics.mean(error_rates)
            error_std = statistics.stdev(error_rates) if len(error_rates) > 1 else 0.0
            
            # Check for anomalies (using Z-score)
            latency_z = abs(metrics.latency_mean - latency_mean) / max(latency_std, 0.001)
            error_z = abs(metrics.error_rate - error_mean) / max(error_std, 0.001)
            
            if latency_z > self.config.anomaly_threshold or error_z > self.config.anomaly_threshold:
                logger.warning(
                    f"Performance anomaly detected for {provider_name}: "
                    f"latency_z={latency_z:.2f}, error_z={error_z:.2f}"
                )
                
                with self._lock:
                    self._analytics.anomalies_detected += 1
                
        except Exception as e:
            logger.error(f"Failed to detect performance anomalies: {e}")
    
    async def _update_ml_models(self, provider_name: str, metrics: PerformanceMetrics) -> None:
        """Update machine learning models with new data."""
        try:
            # Create training sample
            sample = {
                'provider': provider_name,
                'timestamp': metrics.timestamp,
                'latency': metrics.latency_mean,
                'error_rate': metrics.error_rate,
                'throughput': metrics.requests_per_second,
                'cost': metrics.cost_per_request,
                'quality': metrics.response_quality_score,
                'reliability': metrics.success_rate
            }
            
            with self._lock:
                self._training_data.append(sample)
                
                # Limit training data size
                if len(self._training_data) > self.config.performance_history_size:
                    self._training_data = self._training_data[-self.config.performance_history_size:]
                
        except Exception as e:
            logger.error(f"Failed to update ML models: {e}")
    
    async def _update_integrated_components(self, provider_name: str, metrics: PerformanceMetrics) -> None:
        """Update integrated components with new performance data."""
        try:
            # Update provider registry
            success = metrics.error_rate < 0.5  # Simple success determination
            self._provider_registry.record_provider_performance(
                provider_name, success, metrics.latency_mean
            )
            
        except Exception as e:
            logger.error(f"Failed to update integrated components: {e}")
    
    async def _predict_optimal_strategy(
        self,
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> Optional[AdaptiveStrategy]:
        """Predict optimal strategy using ML models."""
        try:
            if not self.config.enable_ml_optimization:
                return None
            
            # This is a simplified prediction
            # In a real implementation, this would use trained ML models
            with self._lock:
                if len(self._training_data) < self.config.min_training_samples:
                    return None
                
                # Simple heuristic based on recent performance
                recent_data = self._training_data[-100:]
                
                # Calculate performance by strategy (simplified)
                strategy_performance = defaultdict(list)
                for sample in recent_data:
                    # This would need actual strategy data in real implementation
                    strategy_performance[AdaptiveStrategy.BALANCED].append(
                        sample['latency'] + sample['error_rate'] * 10
                    )
                
                # Find best performing strategy
                best_strategy = None
                best_performance = float('inf')
                
                for strategy, performances in strategy_performance.items():
                    if performances:
                        avg_performance = statistics.mean(performances)
                        if avg_performance < best_performance:
                            best_performance = avg_performance
                            best_strategy = strategy
                
                return best_strategy
                
        except Exception as e:
            logger.error(f"Failed to predict optimal strategy: {e}")
            return None
    
    async def _predict_provider_performance(
        self,
        provider_name: str,
        context: str,
        requirements: Optional[Dict[str, Any]]
    ) -> Tuple[float, float]:
        """Predict provider performance using ML models."""
        try:
            # Check cache first
            cache_key = f"{provider_name}_{context}"
            if cache_key in self._prediction_cache:
                cached_prediction, cached_time = self._prediction_cache[cache_key]
                if time.time() - cached_time < 60:  # Cache for 1 minute
                    return cached_prediction, 0.8  # Return tuple with confidence
            
            # Get historical performance
            history = self._performance_history.get(provider_name, deque())
            if len(history) < 5:
                return 0.5, 0.1  # Low confidence with little data
            
            # Simple prediction based on recent performance
            recent_metrics = list(history)[-10:]
            
            # Calculate performance score
            performance_scores = []
            for metrics in recent_metrics:
                score = (
                    (1.0 - min(metrics.latency_mean / 5.0, 1.0)) * 0.3 +  # Latency
                    (1.0 - metrics.error_rate) * 0.3 +                    # Error rate
                    metrics.success_rate * 0.2 +                              # Success rate
                    metrics.user_satisfaction_score * 0.2                     # User satisfaction
                )
                performance_scores.append(score)
            
            # Predict future performance (simple trend)
            if len(performance_scores) >= 3:
                recent_trend = performance_scores[-1] - performance_scores[-3]
                prediction = performance_scores[-1] + recent_trend * 0.5
            else:
                prediction = statistics.mean(performance_scores)
            
            # Calculate confidence based on variance
            if len(performance_scores) > 1:
                variance = statistics.variance(performance_scores)
                confidence = max(0.1, 1.0 - min(variance * 10, 0.9))
            else:
                confidence = 0.1
            
            # Cache prediction
            self._prediction_cache[cache_key] = (prediction, time.time())
            
            return max(0.0, min(1.0, prediction)), confidence
            
        except Exception as e:
            logger.error(f"Failed to predict provider performance: {e}")
            return 0.5, 0.1
    
    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction from values."""
        if len(values) < 3:
            return "stable"
        
        # Simple linear regression to determine trend
        n = len(values)
        x_values = list(range(n))
        
        # Calculate slope
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(values)
        
        numerator = sum((x_values[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return "stable"
        
        slope = numerator / denominator
        
        # Determine trend based on slope magnitude
        if abs(slope) < 0.01:
            return "stable"
        elif slope > 0:
            return "improving"  # For metrics where higher is better
        else:
            return "degrading"
    
    def _calculate_overall_trend(self, trends: List[str]) -> str:
        """Calculate overall trend from multiple trend indicators."""
        if not trends:
            return "stable"
        
        improving_count = trends.count("improving")
        degrading_count = trends.count("degrading")
        stable_count = trends.count("stable")
        
        if improving_count > degrading_count and improving_count > stable_count:
            return "improving"
        elif degrading_count > improving_count and degrading_count > stable_count:
            return "degrading"
        else:
            return "stable"
    
    async def _analyze_current_performance(self) -> Dict[str, Any]:
        """Analyze current system performance."""
        try:
            with self._lock:
                if not self._provider_metrics:
                    return {}
                
                # Calculate aggregate metrics
                all_metrics = list(self._provider_metrics.values())
                
                aggregate_performance = {
                    'total_providers': len(all_metrics),
                    'average_latency': statistics.mean([m.latency_mean for m in all_metrics]),
                    'average_error_rate': statistics.mean([m.error_rate for m in all_metrics]),
                    'average_throughput': statistics.mean([m.requests_per_second for m in all_metrics]),
                    'average_cost': statistics.mean([m.cost_per_request for m in all_metrics]),
                    'average_quality': statistics.mean([m.response_quality_score for m in all_metrics]),
                    'average_reliability': statistics.mean([m.success_rate for m in all_metrics])
                }
                
                # Identify best and worst performers
                latency_ranking = sorted(all_metrics, key=lambda m: m.latency_mean)
                cost_ranking = sorted(all_metrics, key=lambda m: m.cost_per_request)
                quality_ranking = sorted(all_metrics, key=lambda m: m.response_quality_score, reverse=True)
                
                aggregate_performance.update({
                    'best_latency': latency_ranking[0].provider_name if latency_ranking else None,
                    'worst_latency': latency_ranking[-1].provider_name if latency_ranking else None,
                    'best_cost': cost_ranking[0].provider_name if cost_ranking else None,
                    'worst_cost': cost_ranking[-1].provider_name if cost_ranking else None,
                    'best_quality': quality_ranking[0].provider_name if quality_ranking else None,
                    'worst_quality': quality_ranking[-1].provider_name if quality_ranking else None
                })
                
                return aggregate_performance
                
        except Exception as e:
            logger.error(f"Failed to analyze current performance: {e}")
            return {}
    
    async def _generate_optimization_recommendations(
        self,
        current_performance: Dict[str, Any],
        objectives: List[OptimizationObjective]
    ) -> List[Dict[str, Any]]:
        """Generate optimization recommendations based on objectives."""
        try:
            recommendations = []
            
            for objective in objectives:
                if objective == OptimizationObjective.MINIMIZE_LATENCY:
                    if current_performance.get('average_latency', 0) > 2.0:
                        recommendations.append({
                            'objective': objective.name,
                            'recommendation': 'Switch to latency-optimized routing strategy',
                            'expected_improvement': '30-50% latency reduction',
                            'priority': 'high'
                        })
                
                elif objective == OptimizationObjective.MINIMIZE_COST:
                    if current_performance.get('average_cost', 0) > 0.01:
                        recommendations.append({
                            'objective': objective.name,
                            'recommendation': 'Enable cost-optimized routing for non-critical requests',
                            'expected_improvement': '40-60% cost reduction',
                            'priority': 'medium'
                        })
                
                elif objective == OptimizationObjective.MAXIMIZE_QUALITY:
                    if current_performance.get('average_quality', 0) < 0.8:
                        recommendations.append({
                            'objective': objective.name,
                            'recommendation': 'Prioritize high-quality providers for critical requests',
                            'expected_improvement': '20-30% quality improvement',
                            'priority': 'high'
                        })
                
                elif objective == OptimizationObjective.MAXIMIZE_RELIABILITY:
                    if current_performance.get('average_reliability', 0) < 0.9:
                        recommendations.append({
                            'objective': objective.name,
                            'recommendation': 'Implement aggressive failover and retry mechanisms',
                            'expected_improvement': '15-25% reliability improvement',
                            'priority': 'high'
                        })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to generate optimization recommendations: {e}")
            return []
    
    async def _apply_optimizations(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply optimization recommendations."""
        try:
            applied = []
            
            for rec in recommendations:
                try:
                    # Apply optimization based on recommendation
                    if 'latency-optimized' in rec.get('recommendation', ''):
                        self._current_strategy = AdaptiveStrategy.LATENCY_OPTIMIZED
                        applied.append(rec)
                    
                    elif 'cost-optimized' in rec.get('recommendation', ''):
                        self._current_strategy = AdaptiveStrategy.COST_OPTIMIZED
                        applied.append(rec)
                    
                    elif 'quality' in rec.get('recommendation', ''):
                        self._current_strategy = AdaptiveStrategy.QUALITY_OPTIMIZED
                        applied.append(rec)
                    
                except Exception as e:
                    logger.error(f"Failed to apply optimization: {e}")
            
            return applied
            
        except Exception as e:
            logger.error(f"Failed to apply optimizations: {e}")
            return []
    
    async def _optimization_loop(self) -> None:
        """Background optimization loop."""
        logger.info("Performance optimization loop started")
        
        while self._monitoring_active:
            try:
                # Analyze current performance
                current_performance = await self._analyze_current_performance()
                
                # Generate and apply optimizations
                recommendations = await self._generate_optimization_recommendations(
                    current_performance, [OptimizationObjective.BALANCE_ALL]
                )
                
                if recommendations:
                    applied = await self._apply_optimizations(recommendations)
                    if applied:
                        logger.info(f"Applied {len(applied)} optimizations")
                
                # Sleep until next optimization
                await asyncio.sleep(self.config.optimization_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Performance optimization loop stopped")
    
    async def _ml_training_loop(self) -> None:
        """Background ML model training loop."""
        logger.info("ML training loop started")
        
        while self._monitoring_active:
            try:
                with self._lock:
                    if len(self._training_data) >= self.config.min_training_samples:
                        # Train models (simplified implementation)
                        await self._train_ml_models()
                
                # Sleep until next training
                await asyncio.sleep(self.config.ml_model_update_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ML training loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("ML training loop stopped")
    
    async def _train_ml_models(self) -> None:
        """Train machine learning models."""
        try:
            # This is a simplified implementation
            # In a real system, this would train actual ML models
            
            logger.debug(f"Training ML models with {len(self._training_data)} samples")
            
            # Clear prediction cache when models are updated
            self._prediction_cache.clear()
            
        except Exception as e:
            logger.error(f"Failed to train ML models: {e}")
    
    async def _reporting_loop(self) -> None:
        """Background reporting loop."""
        logger.info("Performance reporting loop started")
        
        while self._monitoring_active:
            try:
                # Generate performance report
                report = await self._generate_performance_report()
                
                # Log report summary
                logger.info(f"Performance report: {report.get('summary', {})}")
                
                # Sleep until next report
                await asyncio.sleep(self.config.report_generation_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reporting loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Performance reporting loop stopped")
    
    async def _generate_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        try:
            with self._lock:
                report = {
                    'timestamp': time.time(),
                    'summary': {
                        'total_requests': self._analytics.total_requests,
                        'success_rate': (
                            self._analytics.successful_requests / 
                            max(self._analytics.total_requests, 1)
                        ),
                        'average_latency': self._analytics.average_latency,
                        'anomalies_detected': self._analytics.anomalies_detected
                    },
                    'providers': {},
                    'strategies': self._analytics.strategy_usage,
                    'recommendations': self._analytics.optimization_suggestions
                }
                
                # Add provider-specific data
                for provider_name, metrics in self._provider_metrics.items():
                    report['providers'][provider_name] = {
                        'latency': metrics.latency_mean,
                        'error_rate': metrics.error_rate,
                        'throughput': metrics.requests_per_second,
                        'cost': metrics.cost_per_request,
                        'quality': metrics.response_quality_score,
                        'reliability': metrics.success_rate
                    }
                
                return report
                
        except Exception as e:
            logger.error(f"Failed to generate performance report: {e}")
            return {'error': str(e), 'timestamp': time.time()}
    
    def _on_fallback_switch(self, fallback_result) -> None:
        """Handle fallback switch events."""
        try:
            # Update analytics
            with self._lock:
                self._analytics.total_requests += 1
                if fallback_result.success:
                    self._analytics.successful_requests += 1
                else:
                    self._analytics.failed_requests += 1
            
        except Exception as e:
            logger.error(f"Failed to handle fallback switch: {e}")
    
    def _on_health_alert(self, health_alert) -> None:
        """Handle health alert events."""
        try:
            # Adjust routing based on health alerts
            if health_alert.level.value == "critical":
                # Reduce priority of unhealthy components
                logger.warning(f"Critical health alert: {health_alert.message}")
                
        except Exception as e:
            logger.error(f"Failed to handle health alert: {e}")
    
    def _on_provider_switch(self, switch_result) -> None:
        """Handle provider switch events."""
        try:
            # Update analytics
            with self._lock:
                self._analytics.total_requests += 1
                if switch_result.success:
                    self._analytics.successful_requests += 1
                else:
                    self._analytics.failed_requests += 1
            
        except Exception as e:
            logger.error(f"Failed to handle provider switch: {e}")


# Global instance
_performance_adaptive_router: Optional[PerformanceAdaptiveRouter] = None
_router_lock = threading.RLock()


def get_performance_adaptive_router(config: Optional[AdaptiveConfig] = None) -> PerformanceAdaptiveRouter:
    """Get or create global performance adaptive router instance."""
    global _performance_adaptive_router
    if _performance_adaptive_router is None:
        with _router_lock:
            if _performance_adaptive_router is None:
                _performance_adaptive_router = PerformanceAdaptiveRouter(config)
    return _performance_adaptive_router


async def initialize_performance_adaptive_router(config: Optional[AdaptiveConfig] = None) -> PerformanceAdaptiveRouter:
    """Initialize performance adaptive router system."""
    router = get_performance_adaptive_router(config)
    await router.start_monitoring()
    logger.info("Performance adaptive router system initialized")
    return router


# Export main classes for easy import
__all__ = [
    "AdaptiveStrategy",
    "PerformanceMetricType",
    "OptimizationObjective",
    "PerformanceMetrics",
    "PerformanceThreshold",
    "RoutingDecision",
    "RoutingAnalytics",
    "AdaptiveConfig",
    "PerformanceAdaptiveRouter",
    "get_performance_adaptive_router",
    "initialize_performance_adaptive_router",
]