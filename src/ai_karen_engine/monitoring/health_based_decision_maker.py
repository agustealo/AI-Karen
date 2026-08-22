"""
Health-Based Decision Making System for Karen AI Intelligent Fallback

This module provides intelligent decision-making capabilities based on comprehensive
health monitoring data, enabling automatic provider selection, fallback strategies,
and performance optimization based on real-time health status.

Features:
- Health-aware provider selection and fallback
- Automatic switching based on health degradation
- Performance optimization based on health metrics
- Graceful degradation strategies
- Predictive decision making based on health trends
"""

import asyncio
import logging
import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Callable, Union
from collections import defaultdict, deque

from .comprehensive_health_monitor import (
    HealthStatus, HealthCheckType, HealthCheckResult, AlertLevel,
    get_comprehensive_health_monitor
)
from ..integrations.intelligent_provider_registry import (
    ProviderType, ProviderPriority, get_intelligent_provider_registry
)
from ..integrations.capability_aware_selector import (
    SelectionCriteria, SelectionStrategy, RequestContext, get_capability_selector
)
from ..monitoring.network_connectivity import NetworkStatus, get_network_monitor

logger = logging.getLogger(__name__)


class DecisionStrategy(Enum):
    """Decision-making strategies based on health data."""
    HEALTH_FIRST = auto()  # Prioritize healthiest options
    PERFORMANCE_FIRST = auto()  # Prioritize fastest response
    RELIABILITY_FIRST = auto()  # Prioritize most reliable
    COST_FIRST = auto()  # Prioritize cheapest options
    ADAPTIVE = auto()  # Adaptive based on context and health


class DecisionTrigger(Enum):
    """Triggers for health-based decisions."""
    HEALTH_DEGRADATION = auto()  # Health score drops below threshold
    PERFORMANCE_DEGRADATION = auto()  # Response time increases
    PROVIDER_FAILURE = auto()  # Provider becomes unavailable
    NETWORK_CHANGE = auto()  # Network status changes
    RESOURCE_PRESSURE = auto()  # System resources under pressure
    PREDICTIVE_FAILURE = auto()  # Predicted future failure


@dataclass
class HealthDecision:
    """Decision made based on health monitoring data."""
    decision_id: str
    trigger: DecisionTrigger
    strategy: DecisionStrategy
    action: str  # Description of action taken
    component: str  # Component affected
    old_provider: Optional[str] = None
    new_provider: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    expected_impact: str = "neutral"  # "positive", "neutral", "negative"
    rollback_available: bool = True


@dataclass
class DecisionThresholds:
    """Thresholds for triggering health-based decisions."""
    health_degradation_threshold: float = 0.7  # Health score below this triggers decisions
    performance_degradation_threshold: float = 2.0  # Response time above this triggers decisions
    consecutive_failure_threshold: int = 3  # Consecutive failures trigger fallback
    resource_pressure_threshold: float = 0.8  # Resource usage above this triggers decisions
    prediction_confidence_threshold: float = 0.8  # Confidence above this triggers predictive decisions
    decision_cooldown: float = 60.0  # Seconds between similar decisions


@dataclass
class DecisionConfig:
    """Configuration for health-based decision making."""
    enable_automatic_switching: bool = True
    enable_predictive_decisions: bool = True
    enable_graceful_degradation: bool = True
    max_consecutive_failures: int = 5
    fallback_strategy: str = "health_aware"  # health_aware, cost_aware, performance_aware
    decision_history_size: int = 100
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)


class HealthBasedDecisionMaker:
    """
    Health-based decision making system for intelligent fallback.
    
    Analyzes health monitoring data to make intelligent decisions about
    provider selection, fallback strategies, and performance optimization.
    """
    
    def __init__(self, config: Optional[DecisionConfig] = None):
        """Initialize health-based decision maker."""
        self.config = config or DecisionConfig()
        
        # Component integrations
        self._health_monitor = get_comprehensive_health_monitor()
        self._provider_registry = get_intelligent_provider_registry()
        self._capability_selector = get_capability_selector()
        self._network_monitor = get_network_monitor()
        
        # Decision history
        self._decision_history: deque = deque(maxlen=self.config.decision_history_size)
        self._last_decisions: Dict[str, float] = {}
        
        # Decision callbacks
        self._decision_callbacks: List[Callable[[HealthDecision], None]] = []
        
        # Current state tracking
        self._current_providers: Dict[str, str] = {}
        self._fallback_chains: Dict[str, List[str]] = {}
        
        logger.info("Health-based decision maker initialized")
    
    def register_decision_callback(self, callback: Callable[[HealthDecision], None]) -> None:
        """Register callback for health-based decisions."""
        self._decision_callbacks.append(callback)
    
    def get_current_provider(self, context: str = "default") -> Optional[str]:
        """Get current provider for a context."""
        return self._current_providers.get(context)
    
    def get_decision_history(self, limit: int = 10) -> List[HealthDecision]:
        """Get recent decision history."""
        return list(self._decision_history)[-limit:]
    
    def get_decision_analytics(self) -> Dict[str, Any]:
        """Get analytics about decision making."""
        if not self._decision_history:
            return {}
        
        # Decision frequency by trigger
        trigger_counts = defaultdict(int)
        strategy_counts = defaultdict(int)
        impact_counts = defaultdict(int)
        
        for decision in self._decision_history:
            trigger_counts[decision.trigger.name] += 1
            strategy_counts[decision.strategy.name] += 1
            impact_counts[decision.expected_impact] += 1
        
        return {
            'total_decisions': len(self._decision_history),
            'trigger_distribution': dict(trigger_counts),
            'strategy_distribution': dict(strategy_counts),
            'impact_distribution': dict(impact_counts),
            'average_confidence': sum(d.confidence for d in self._decision_history) / len(self._decision_history),
            'recent_decisions': [
                {
                    'action': d.action,
                    'trigger': d.trigger.name,
                    'confidence': d.confidence,
                    'timestamp': d.timestamp
                }
                for d in list(self._decision_history)[-5:]
            ]
        }
    
    async def make_provider_decision(
        self,
        context: str = "default",
        required_capabilities: Optional[Set[str]] = None,
        strategy: Optional[DecisionStrategy] = None
    ) -> Optional[HealthDecision]:
        """
        Make provider selection decision based on health data.
        
        Args:
            context: Usage context (e.g., 'chat', 'code', 'embedding')
            required_capabilities: Required capabilities for the context
            strategy: Decision strategy to use
            
        Returns:
            Health decision if action taken, None otherwise
        """
        current_time = time.time()
        
        # Check cooldown
        last_decision_time = self._last_decisions.get(f"provider_{context}", 0.0)
        if current_time - last_decision_time < self.config.thresholds.decision_cooldown:
            logger.debug(f"Provider decision for {context} in cooldown period")
            return None
        
        # Get current health status
        health_summary = self._health_monitor.get_health_summary()
        overall_status = HealthStatus(health_summary.get('overall_status', HealthStatus.UNKNOWN.value))
        overall_score = health_summary.get('overall_score', 0.0)
        
        # Get current provider
        current_provider = self._current_providers.get(context)
        
        # Determine if decision is needed
        trigger = self._analyze_decision_triggers(health_summary, current_provider)
        if not trigger:
            return None
        
        # Select strategy if not provided
        if not strategy:
            strategy = self._select_decision_strategy(overall_status, context)
        
        # Make decision
        decision = await self._make_provider_decision(
            context, required_capabilities, strategy, trigger, health_summary
        )
        
        if decision:
            # Record decision
            self._record_decision(decision)
            self._last_decisions[f"provider_{context}"] = current_time
            
            logger.info(f"Health-based provider decision: {decision.action} (trigger: {trigger.name})")
        
        return decision
    
    def _analyze_decision_triggers(
        self,
        health_summary: Dict[str, Any],
        current_provider: Optional[str]
    ) -> Optional[DecisionTrigger]:
        """Analyze if a decision should be triggered based on health data."""
        overall_status = HealthStatus(health_summary.get('overall_status', HealthStatus.UNKNOWN.value))
        overall_score = health_summary.get('overall_score', 0.0)
        
        # Check for health degradation
        if overall_score < self.config.thresholds.health_degradation_threshold:
            return DecisionTrigger.HEALTH_DEGRADATION
        
        # Check for provider-specific issues
        if current_provider:
            provider_health = self._health_monitor.get_component_health(current_provider)
            if provider_health and provider_health.status == HealthStatus.UNHEALTHY:
                return DecisionTrigger.PROVIDER_FAILURE
        
        # Check for network changes
        network_status = self._network_monitor.get_current_status()
        if network_status in [NetworkStatus.OFFLINE, NetworkStatus.DEGRADED]:
            return DecisionTrigger.NETWORK_CHANGE
        
        # Check for resource pressure
        components = health_summary.get('components', {})
        resource_component = components.get('RESOURCE', {})
        resource_score = resource_component.get('score', 1.0)
        if resource_score < (1.0 - self.config.thresholds.resource_pressure_threshold):
            return DecisionTrigger.RESOURCE_PRESSURE
        
        # Check for predictive failures
        if self.config.enable_predictive_decisions:
            predictive_trigger = self._check_predictive_triggers(health_summary)
            if predictive_trigger:
                return predictive_trigger
        
        return None
    
    def _select_decision_strategy(
        self,
        overall_status: HealthStatus,
        context: str
    ) -> DecisionStrategy:
        """Select appropriate decision strategy based on health status and context."""
        if overall_status == HealthStatus.UNHEALTHY:
            return DecisionStrategy.HEALTH_FIRST
        elif overall_status == HealthStatus.DEGRADED:
            if context in ['realtime', 'conversation']:
                return DecisionStrategy.PERFORMANCE_FIRST
            else:
                return DecisionStrategy.RELIABILITY_FIRST
        else:  # HEALTHY
            if context in ['batch', 'analytics']:
                return DecisionStrategy.COST_FIRST
            else:
                return DecisionStrategy.ADAPTIVE
    
    async def _make_provider_decision(
        self,
        context: str,
        required_capabilities: Optional[Set[str]],
        strategy: DecisionStrategy,
        trigger: DecisionTrigger,
        health_summary: Dict[str, Any]
    ) -> Optional[HealthDecision]:
        """Make actual provider decision based on strategy."""
        current_provider = self._current_providers.get(context)
        
        # Get available providers
        try:
            # Create selection criteria based on strategy
            if strategy == DecisionStrategy.HEALTH_FIRST:
                criteria = SelectionCriteria(
                    required_capabilities=[
                        {"name": cap, "priority": 1.0}
                        for cap in (required_capabilities or set())
                    ],
                    context=self._map_context_to_request_context(context),
                    strategy=SelectionStrategy.RELIABILITY_FIRST
                )
            elif strategy == DecisionStrategy.PERFORMANCE_FIRST:
                criteria = SelectionCriteria(
                    required_capabilities=[
                        {"name": cap, "priority": 1.0}
                        for cap in (required_capabilities or set())
                    ],
                    context=self._map_context_to_request_context(context),
                    strategy=SelectionStrategy.PERFORMANCE_FIRST
                )
            elif strategy == DecisionStrategy.COST_FIRST:
                criteria = SelectionCriteria(
                    required_capabilities=[
                        {"name": cap, "priority": 1.0}
                        for cap in (required_capabilities or set())
                    ],
                    context=self._map_context_to_request_context(context),
                    strategy=SelectionStrategy.COST_FIRST
                )
            elif strategy == DecisionStrategy.RELIABILITY_FIRST:
                criteria = SelectionCriteria(
                    required_capabilities=[
                        {"name": cap, "priority": 1.0}
                        for cap in (required_capabilities or set())
                    ],
                    context=self._map_context_to_request_context(context),
                    strategy=SelectionStrategy.RELIABILITY_FIRST
                )
            else:  # ADAPTIVE
                criteria = SelectionCriteria(
                    required_capabilities=[
                        {"name": cap, "priority": 1.0}
                        for cap in (required_capabilities or set())
                    ],
                    context=self._map_context_to_request_context(context),
                    strategy=SelectionStrategy.ADAPTIVE
                )
            
            # Get optimal provider
            try:
                new_provider, provider_score = self._capability_selector.select_provider(criteria)
            except RuntimeError:
                return None
            
            if not new_provider or new_provider == current_provider:
                return None
            
            # Get provider info for decision
            provider_info = self._provider_registry.get_provider_info(new_provider)
            provider_type = provider_info.provider_type.name if provider_info else "unknown"
            
            # Create decision
            decision = HealthDecision(
                decision_id=f"{int(time.time())}_{context}",
                trigger=trigger,
                strategy=strategy,
                action=f"Switch provider from {current_provider} to {new_provider}",
                component="provider_selection",
                old_provider=current_provider,
                new_provider=new_provider,
                reason=self._generate_decision_reason(trigger, strategy, health_summary, provider_score),
                confidence=min(1.0, provider_score.total_score if provider_score else 0.5),
                metadata={
                    'context': context,
                    'provider_type': provider_type,
                    'health_score': provider_score.total_score if provider_score else 0.0,
                    'capabilities_required': list(required_capabilities or set())
                },
                expected_impact="positive" if provider_score and provider_score.total_score > 0.7 else "neutral"
            )
            
            return decision
            
        except Exception as e:
            logger.error(f"Error making provider decision: {e}")
            return None
    
    def _map_context_to_request_context(self, context: str) -> RequestContext:
        """Map decision context to request context."""
        context_mapping = {
            'realtime': RequestContext.REALTIME,
            'batch': RequestContext.BATCH,
            'chat': RequestContext.CONVERSATION,
            'conversation': RequestContext.CONVERSATION,
            'code': RequestContext.CODE,
            'coding': RequestContext.CODE,
            'programming': RequestContext.CODE,
            'embedding': RequestContext.EMBEDDING,
            'embeddings': RequestContext.EMBEDDING,
            'analytics': RequestContext.ANALYTICAL,
            'analysis': RequestContext.ANALYTICAL,
            'creative': RequestContext.CREATIVE,
            'generation': RequestContext.CREATIVE
        }
        return context_mapping.get(context, RequestContext.REALTIME)
    
    def _generate_decision_reason(
        self,
        trigger: DecisionTrigger,
        strategy: DecisionStrategy,
        health_summary: Dict[str, Any],
        provider_score: Optional[Any]
    ) -> str:
        """Generate human-readable reason for decision."""
        base_reason = f"Trigger: {trigger.name}, Strategy: {strategy.name}"
        
        if trigger == DecisionTrigger.HEALTH_DEGRADATION:
            overall_score = health_summary.get('overall_score', 0.0)
            base_reason += f", Overall health score: {overall_score:.3f}"
        elif trigger == DecisionTrigger.PROVIDER_FAILURE:
            base_reason += f", Current provider unhealthy"
        elif trigger == DecisionTrigger.NETWORK_CHANGE:
            network_status = self._network_monitor.get_current_status()
            base_reason += f", Network status: {network_status.value}"
        elif trigger == DecisionTrigger.RESOURCE_PRESSURE:
            components = health_summary.get('components', {})
            resource_component = components.get('RESOURCE', {})
            resource_score = resource_component.get('score', 1.0)
            base_reason += f", Resource score: {resource_score:.3f}"
        
        if provider_score:
            base_reason += f", Selected provider score: {getattr(provider_score, 'total_score', 0.0):.3f}"
        
        return base_reason
    
    def _check_predictive_triggers(
        self,
        health_summary: Dict[str, Any]
    ) -> Optional[DecisionTrigger]:
        """Check for predictive failure triggers based on trends."""
        if not self.config.enable_predictive_decisions:
            return None
        
        trends = health_summary.get('trends', {})
        
        for component, trend_data in trends.items():
            direction = trend_data.get('direction', 'stable')
            confidence = trend_data.get('confidence', 0.0)
            
            if (direction == 'degrading' and 
                confidence > self.config.thresholds.prediction_confidence_threshold):
                logger.info(f"Predictive failure detected for {component}: {direction} with confidence {confidence}")
                return DecisionTrigger.PREDICTIVE_FAILURE
        
        return None
    
    def _record_decision(self, decision: HealthDecision) -> None:
        """Record a health-based decision."""
        self._decision_history.append(decision)
        
        # Update current provider if applicable
        if decision.new_provider:
            context = decision.metadata.get('context', 'default')
            self._current_providers[context] = decision.new_provider
        
        # Trigger callbacks
        for callback in self._decision_callbacks:
            try:
                callback(decision)
            except Exception as e:
                logger.error(f"Decision callback error: {e}")
    
    def set_fallback_chain(self, context: str, fallback_chain: List[str]) -> None:
        """Set fallback chain for a context."""
        self._fallback_chains[context] = fallback_chain
        logger.info(f"Set fallback chain for {context}: {fallback_chain}")
    
    def get_fallback_chain(self, context: str) -> List[str]:
        """Get fallback chain for a context."""
        return self._fallback_chains.get(context, [])
    
    async def execute_graceful_degradation(
        self,
        context: str,
        degradation_level: float  # 0.0 to 1.0
    ) -> Optional[HealthDecision]:
        """
        Execute graceful degradation strategy.
        
        Args:
            context: Usage context
            degradation_level: Level of degradation (0.0 = none, 1.0 = severe)
            
        Returns:
            Decision if degradation action taken, None otherwise
        """
        if not self.config.enable_graceful_degradation:
            return None
        
        current_provider = self._current_providers.get(context)
        if not current_provider:
            return None
        
        # Determine degradation action based on level
        if degradation_level < 0.3:
            # Light degradation - reduce request frequency
            action = f"Reduce request frequency for {current_provider}"
        elif degradation_level < 0.7:
            # Moderate degradation - switch to lower tier provider
            fallback_chain = self.get_fallback_chain(context)
            if fallback_chain:
                new_provider = fallback_chain[0]
                action = f"Switch to lower tier provider: {new_provider}"
            else:
                action = f"Reduce complexity for {current_provider}"
        else:
            # Severe degradation - switch to most reliable provider
            fallback_chain = self.get_fallback_chain(context)
            if fallback_chain:
                new_provider = fallback_chain[0]
                action = f"Switch to most reliable provider: {new_provider}"
            else:
                action = f"Emergency fallback for {current_provider}"
        
        decision = HealthDecision(
            decision_id=f"{int(time.time())}_{context}_degradation",
            trigger=DecisionTrigger.HEALTH_DEGRADATION,
            strategy=DecisionStrategy.RELIABILITY_FIRST,
            action=action,
            component="graceful_degradation",
            old_provider=current_provider,
            new_provider=new_provider if 'new_provider' in locals() else None,
            reason=f"Graceful degradation level: {degradation_level:.2f}",
            confidence=1.0 - degradation_level,
            metadata={
                'context': context,
                'degradation_level': degradation_level,
                'fallback_chain': self.get_fallback_chain(context)
            },
            expected_impact="positive"
        )
        
        self._record_decision(decision)
        return decision
    
    def get_health_aware_recommendations(self) -> Dict[str, Any]:
        """Get health-aware recommendations for system optimization."""
        health_summary = self._health_monitor.get_health_summary()
        overall_status = HealthStatus(health_summary.get('overall_status', HealthStatus.UNKNOWN.value))
        overall_score = health_summary.get('overall_score', 0.0)
        components = health_summary.get('components', {})
        
        recommendations = []
        
        # Overall recommendations
        if overall_status == HealthStatus.UNHEALTHY:
            recommendations.append({
                'priority': 'critical',
                'category': 'system',
                'message': 'System health is critical - immediate attention required',
                'actions': ['Check network connectivity', 'Verify provider status', 'Monitor system resources']
            })
        elif overall_status == HealthStatus.DEGRADED:
            recommendations.append({
                'priority': 'high',
                'category': 'system',
                'message': 'System performance is degraded',
                'actions': ['Consider fallback providers', 'Optimize resource usage', 'Check for bottlenecks']
            })
        
        # Component-specific recommendations
        for component_name, component_data in components.items():
            status = component_data.get('status', HealthStatus.UNKNOWN.value)
            score = component_data.get('score', 0.0)
            
            if status == HealthStatus.UNHEALTHY.value:
                if component_name == 'NETWORK':
                    recommendations.append({
                        'priority': 'high',
                        'category': 'network',
                        'message': 'Network connectivity issues detected',
                        'actions': ['Check internet connection', 'Verify DNS settings', 'Consider offline providers']
                    })
                elif component_name == 'PROVIDERS':
                    recommendations.append({
                        'priority': 'high',
                        'category': 'providers',
                        'message': 'Provider health issues detected',
                        'actions': ['Check provider configurations', 'Enable fallback chains', 'Review API keys']
                    })
                elif component_name == 'MODELS':
                    recommendations.append({
                        'priority': 'medium',
                        'category': 'models',
                        'message': 'Model cache issues detected',
                        'actions': ['Clear cache', 'Check disk space', 'Verify model integrity']
                    })
                elif component_name == 'RESOURCES':
                    recommendations.append({
                        'priority': 'high',
                        'category': 'resources',
                        'message': 'System resources under pressure',
                        'actions': ['Free up memory', 'Check CPU usage', 'Clear disk space']
                    })
            elif status == HealthStatus.DEGRADED.value and score < 0.6:
                if component_name == 'NETWORK':
                    recommendations.append({
                        'priority': 'medium',
                        'category': 'network',
                        'message': 'Network performance degraded',
                        'actions': ['Check network latency', 'Optimize routing', 'Consider CDN']
                    })
                elif component_name == 'PROVIDERS':
                    recommendations.append({
                        'priority': 'medium',
                        'category': 'providers',
                        'message': 'Provider performance degraded',
                        'actions': ['Review provider metrics', 'Adjust timeouts', 'Consider alternatives']
                    })
        
        return {
            'overall_status': overall_status,
            'overall_score': overall_score,
            'recommendations': recommendations,
            'decision_analytics': self.get_decision_analytics(),
            'current_providers': self._current_providers,
            'fallback_chains': self._fallback_chains
        }


# Global instance
_health_decision_maker: Optional[HealthBasedDecisionMaker] = None
_decision_lock = threading.RLock()


def get_health_decision_maker(config: Optional[DecisionConfig] = None) -> HealthBasedDecisionMaker:
    """Get or create global health decision maker instance."""
    global _health_decision_maker
    if _health_decision_maker is None:
        with _decision_lock:
            if _health_decision_maker is None:
                _health_decision_maker = HealthBasedDecisionMaker(config)
    return _health_decision_maker


def initialize_health_decision_maker(config: Optional[DecisionConfig] = None) -> HealthBasedDecisionMaker:
    """Initialize health-based decision making system."""
    decision_maker = get_health_decision_maker(config)
    logger.info("Health-based decision making system initialized")
    return decision_maker


# Export main classes for easy import
__all__ = [
    "DecisionStrategy",
    "DecisionTrigger",
    "HealthDecision",
    "DecisionThresholds",
    "DecisionConfig",
    "HealthBasedDecisionMaker",
    "get_health_decision_maker",
    "initialize_health_decision_maker",
]