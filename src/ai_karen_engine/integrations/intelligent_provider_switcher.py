"""
Intelligent Provider Switching System for Karen AI Intelligent Fallback

This module provides comprehensive intelligent provider switching that orchestrates
seamless transitions between providers based on network conditions, health status,
and performance metrics.

Features:
- Intelligent provider switching based on network connectivity
- Seamless transition mechanisms with context preservation
- Network-aware decision making with predictive switching
- Comprehensive switching analytics and optimization
- Integration with existing intelligent fallback system components
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import json
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Callable, Union, Awaitable
from collections import defaultdict, deque

from .intelligent_provider_registry import (
    IntelligentProviderRegistry, ProviderType, ProviderPriority,
    get_intelligent_provider_registry
)
from .capability_aware_selector import (
    SelectionCriteria, SelectionStrategy, RequestContext, get_capability_selector
)
from .model_availability_cache import get_model_availability_cache
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

    def _create_context_bridge(self, *args: Any, **kwargs: Any) -> Any:
        return None


def _get_fallback_chain_manager_stub() -> _FallbackChainManagerStub:
    return _FallbackChainManagerStub()

logger = logging.getLogger(__name__)


class SwitchStrategy(Enum):
    """Provider switching strategies."""
    IMMEDIATE = "immediate"      # Switch immediately on trigger
    GRACEFUL = "graceful"        # Wait for optimal moment
    PREDICTIVE = "predictive"     # Switch before failure
    OPPORTUNISTIC = "opportunistic"  # Switch when better option available


class SwitchTriggerType(Enum):
    """Triggers for provider switching."""
    NETWORK_CHANGE = auto()        # Network status changed
    HEALTH_DEGRADATION = auto()   # Provider health degraded
    PERFORMANCE_DEGRADATION = auto()  # Performance dropped
    PREDICTIVE_FAILURE = auto()   # Predicted future failure
    MANUAL_OVERRIDE = auto()        # Manual intervention
    COST_OPTIMIZATION = auto()     # Better cost option available
    CAPABILITY_MISMATCH = auto()   # Required capabilities not available


@dataclass
class SwitchTrigger:
    """Conditions that trigger a provider switch."""
    trigger_type: SwitchTriggerType
    threshold: float = 0.0
    conditions: Dict[str, Any] = field(default_factory=dict)
    cooldown_period: float = 60.0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SwitchResult:
    """Result of a provider switch operation."""
    switch_id: str
    success: bool
    old_provider: Optional[str]
    new_provider: Optional[str]
    trigger: SwitchTriggerType
    strategy: SwitchStrategy
    switch_time: float
    total_time: float
    context_preserved: bool = True
    capabilities_preserved: bool = True
    performance_impact: float = 0.0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SwitchContext:
    """Context maintained during provider switches."""
    session_id: str
    user_context: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    active_requests: Dict[str, Any] = field(default_factory=dict)
    capability_requirements: Set[str] = field(default_factory=set)
    performance_constraints: Dict[str, float] = field(default_factory=dict)
    cost_constraints: Dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


@dataclass
class SwitchMetrics:
    """Metrics for tracking switch performance."""
    total_switches: int = 0
    successful_switches: int = 0
    failed_switches: int = 0
    average_switch_time: float = 0.0
    average_downtime: float = 0.0
    context_preservation_rate: float = 1.0
    capability_preservation_rate: float = 1.0
    switch_frequency: Dict[str, int] = field(default_factory=dict)
    trigger_frequency: Dict[SwitchTriggerType, int] = field(default_factory=dict)
    performance_impacts: List[float] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


@dataclass
class SwitchConfig:
    """Configuration for intelligent provider switching."""
    enable_automatic_switching: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_AUTOMATIC_SWITCHING', 'true').lower() == 'true')
    enable_predictive_switching: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_PREDICTIVE_SWITCHING', 'true').lower() == 'true')
    enable_hot_switching: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_ENABLE_HOT_SWITCHING', 'true').lower() == 'true')
    max_concurrent_switches: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_MAX_CONCURRENT_SWITCHES', '3')))
    switch_timeout: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_SWITCH_TIMEOUT', '30.0')))
    cooldown_period: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_SWITCH_COOLDOWN', '60.0')))
    health_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_HEALTH_THRESHOLD', '0.7')))
    performance_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_PERFORMANCE_THRESHOLD', '2.0')))
    prediction_confidence_threshold: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_PREDICTION_CONFIDENCE', '0.8')))
    context_cache_ttl: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_CONTEXT_CACHE_TTL', '3600.0')))
    analytics_history_size: int = field(default_factory=lambda: 
        int(os.environ.get('KAREN_ANALYTICS_HISTORY_SIZE', '1000')))
    optimization_interval: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_OPTIMIZATION_INTERVAL', '300.0')))
    network_aware_switching: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_NETWORK_AWARE_SWITCHING', 'true').lower() == 'true')
    cost_optimization_enabled: bool = field(default_factory=lambda: 
        os.environ.get('KAREN_COST_OPTIMIZATION', 'true').lower() == 'true')
    graceful_transition_timeout: float = field(default_factory=lambda: 
        float(os.environ.get('KAREN_GRACEFUL_TRANSITION_TIMEOUT', '10.0')))


class IntelligentProviderSwitcher:
    """
    Intelligent provider switching system that orchestrates seamless transitions
    between providers based on network conditions, health status, and performance metrics.
    
    This system provides:
    - Real-time network-aware provider switching
    - Predictive switching based on usage patterns and trends
    - Seamless context preservation during transitions
    - Comprehensive analytics and optimization
    - Integration with all existing fallback system components
    """
    
    def __init__(self, config: Optional[SwitchConfig] = None):
        """Initialize intelligent provider switcher."""
        self.config = config or SwitchConfig()
        
        # Core state
        self._active_switches: Dict[str, asyncio.Task] = {}
        self._switch_contexts: Dict[str, SwitchContext] = {}
        self._switch_history: deque = deque(maxlen=self.config.analytics_history_size)
        self._last_switch_times: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        # Component integrations
        self._provider_registry = get_intelligent_provider_registry()
        self._capability_selector = get_capability_selector()
        self._model_cache = get_model_availability_cache()
        self._fallback_manager = _get_fallback_chain_manager_stub()
        self._network_monitor = get_network_monitor()
        self._health_monitor = get_comprehensive_health_monitor()
        self._decision_maker = get_health_decision_maker()
        
        # Switch triggers and conditions
        self._switch_triggers: List[SwitchTrigger] = []
        self._trigger_handlers: Dict[SwitchTriggerType, Callable] = {}
        self._setup_default_triggers()
        
        # Metrics and analytics
        self._metrics = SwitchMetrics()
        self._switch_callbacks: List[Callable[[SwitchResult], None]] = []
        
        # Background tasks
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._optimization_task: Optional[asyncio.Task] = None
        self._switch_semaphore = asyncio.Semaphore(self.config.max_concurrent_switches)
        
        # Network state tracking
        self._network_state = {
            'status': NetworkStatus.UNKNOWN,
            'last_change': time.time(),
            'quality_score': 1.0,
            'bandwidth_estimate': 0.0,
            'latency_estimate': 0.0
        }
        
        logger.info("Intelligent provider switcher initialized")
    
    async def start_monitoring(self) -> None:
        """Start background monitoring and optimization."""
        if self._monitoring_active:
            logger.warning("Provider switcher monitoring already active")
            return
        
        self._monitoring_active = True
        
        # Start monitoring task
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Start optimization task
        if self.config.optimization_interval > 0:
            self._optimization_task = asyncio.create_task(self._optimization_loop())
        
        # Register network status callback
        self._network_monitor.register_status_callback(self._on_network_status_change)
        
        logger.info("Intelligent provider switcher monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring and optimization."""
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        
        # Cancel background tasks
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._optimization_task:
            self._optimization_task.cancel()
            try:
                await self._optimization_task
            except asyncio.CancelledError:
                pass
        
        # Cancel active switches
        for switch_id, task in self._active_switches.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._active_switches.clear()
        
        logger.info("Intelligent provider switcher monitoring stopped")
    
    def register_switch_callback(self, callback: Callable[[SwitchResult], None]) -> None:
        """Register callback for switch events."""
        self._switch_callbacks.append(callback)
    
    def register_trigger(self, trigger: SwitchTrigger) -> None:
        """Register a custom switch trigger."""
        with self._lock:
            self._switch_triggers.append(trigger)
            logger.info(f"Registered switch trigger: {trigger.trigger_type.name}")
    
    async def switch_provider(
        self,
        context: str,
        new_provider: Optional[str] = None,
        strategy: Optional[SwitchStrategy] = None,
        trigger: Optional[SwitchTrigger] = None,
        reason: str = ""
    ) -> SwitchResult:
        """
        Perform intelligent provider switch.
        
        Args:
            context: Usage context (e.g., 'chat', 'code', 'embedding')
            new_provider: Target provider (None for auto-selection)
            strategy: Switching strategy to use
            trigger: Trigger for the switch
            reason: Human-readable reason for switch
            
        Returns:
            SwitchResult with details of the operation
        """
        switch_id = f"{int(time.time())}_{context}"
        start_time = time.time()
        
        # Check cooldown
        last_switch = self._last_switch_times.get(context, 0.0)
        if time.time() - last_switch < self.config.cooldown_period:
            return SwitchResult(
                switch_id=switch_id,
                success=False,
                old_provider=None,
                new_provider=None,
                trigger=trigger.trigger_type if trigger else SwitchTriggerType.MANUAL_OVERRIDE,
                strategy=strategy or SwitchStrategy.IMMEDIATE,
                switch_time=0.0,
                total_time=0.0,
                error_message="Switch in cooldown period"
            )
        
        # Get current provider
        current_provider = self._decision_maker.get_current_provider(context)
        
        # Auto-select provider if not specified
        if not new_provider:
            new_provider = await self._select_optimal_provider(context, strategy)
            if not new_provider:
                return SwitchResult(
                    switch_id=switch_id,
                    success=False,
                    old_provider=current_provider,
                    new_provider=None,
                    trigger=trigger.trigger_type if trigger else SwitchTriggerType.MANUAL_OVERRIDE,
                    strategy=strategy or SwitchStrategy.IMMEDIATE,
                    switch_time=0.0,
                    total_time=0.0,
                    error_message="No suitable provider found"
                )
        
        # Check if switch is needed
        if new_provider == current_provider:
            return SwitchResult(
                switch_id=switch_id,
                success=True,
                old_provider=current_provider,
                new_provider=current_provider,
                trigger=trigger.trigger_type if trigger else SwitchTriggerType.MANUAL_OVERRIDE,
                strategy=strategy or SwitchStrategy.IMMEDIATE,
                switch_time=0.0,
                total_time=0.0,
                error_message="Already using optimal provider"
            )
        
        # Perform switch with semaphore to limit concurrent switches
        async with self._switch_semaphore:
            try:
                result = await self._perform_switch(
                    switch_id, context, current_provider, new_provider,
                    strategy or SwitchStrategy.GRACEFUL,
                    trigger.trigger_type if trigger else SwitchTriggerType.MANUAL_OVERRIDE,
                    reason
                )
                
                # Update last switch time
                self._last_switch_times[context] = time.time()
                
                # Record switch
                self._record_switch(result)
                
                # Trigger callbacks
                for callback in self._switch_callbacks:
                    try:
                        callback(result)
                    except Exception as e:
                        logger.error(f"Switch callback error: {e}")
                
                return result
                
            except Exception as e:
                error_result = SwitchResult(
                    switch_id=switch_id,
                    success=False,
                    old_provider=current_provider,
                    new_provider=new_provider,
                    trigger=trigger.trigger_type if trigger else SwitchTriggerType.MANUAL_OVERRIDE,
                    strategy=strategy or SwitchStrategy.IMMEDIATE,
                    switch_time=time.time() - start_time,
                    total_time=time.time() - start_time,
                    error_message=str(e)
                )
                
                self._record_switch(error_result)
                return error_result
    
    async def _select_optimal_provider(
        self,
        context: str,
        strategy: Optional[SwitchStrategy] = None
    ) -> Optional[str]:
        """Select optimal provider based on current conditions."""
        try:
            # Get current network status
            network_status = self._network_monitor.get_current_status()
            
            # Get current provider
            current_provider = self._decision_maker.get_current_provider(context)
            
            # Create selection criteria based on strategy
            if strategy == SwitchStrategy.PREDICTIVE:
                selection_strategy = SelectionStrategy.RELIABILITY_FIRST
            elif strategy == SwitchStrategy.OPPORTUNISTIC:
                selection_strategy = SelectionStrategy.COST_FIRST
            elif strategy == SwitchStrategy.GRACEFUL:
                selection_strategy = SelectionStrategy.PERFORMANCE_FIRST
            else:  # IMMEDIATE
                selection_strategy = SelectionStrategy.ADAPTIVE
            
            # Map context to request context
            request_context = self._map_context_to_request_context(context)
            
            # Get capability requirements from context
            switch_context = self._get_or_create_switch_context(context)
            required_capabilities = switch_context.capability_requirements
            
            # Create selection criteria
            from .capability_aware_selector import CapabilityRequirement
            criteria = SelectionCriteria(
                required_capabilities=[
                    CapabilityRequirement(name=cap, priority=1.0, min_quality=0.7)
                    for cap in required_capabilities
                ],
                context=request_context,
                strategy=selection_strategy,
                network_preference="auto" if network_status == NetworkStatus.ONLINE else "offline",
                excluded_providers=[current_provider] if current_provider else []
            )
            
            # Get optimal provider
            provider_name, provider_score = self._capability_selector.select_provider(criteria)
            
            return provider_name
            
        except Exception as e:
            logger.error(f"Error selecting optimal provider: {e}")
            return None
    
    async def _perform_switch(
        self,
        switch_id: str,
        context: str,
        old_provider: Optional[str],
        new_provider: str,
        strategy: SwitchStrategy,
        trigger: SwitchTriggerType,
        reason: str
    ) -> SwitchResult:
        """Perform the actual provider switch."""
        switch_start = time.time()
        
        try:
            # Get or create switch context
            switch_context = self._get_or_create_switch_context(context)
            
            # Prepare for switch based on strategy
            if strategy == SwitchStrategy.GRACEFUL:
                await self._prepare_graceful_switch(context, old_provider, new_provider)
            elif strategy == SwitchStrategy.PREDICTIVE:
                await self._prepare_predictive_switch(context, old_provider, new_provider)
            
            # Preserve context if needed
            context_preserved = await self._preserve_context(context, old_provider, new_provider)
            
            # Check capability preservation
            capabilities_preserved = await self._verify_capability_preservation(
                context, old_provider, new_provider
            )
            
            # Execute the actual switch
            switch_time = await self._execute_switch(context, new_provider)
            
            # Update decision maker with new provider
            self._decision_maker._current_providers[context] = new_provider
            
            # Calculate performance impact
            performance_impact = await self._calculate_performance_impact(
                context, old_provider, new_provider
            )
            
            total_time = time.time() - switch_start
            
            result = SwitchResult(
                switch_id=switch_id,
                success=True,
                old_provider=old_provider,
                new_provider=new_provider,
                trigger=trigger,
                strategy=strategy,
                switch_time=switch_time,
                total_time=total_time,
                context_preserved=context_preserved,
                capabilities_preserved=capabilities_preserved,
                performance_impact=performance_impact,
                metadata={
                    'context': context,
                    'reason': reason,
                    'network_status': self._network_state['status'].value,
                    'network_quality': self._network_state['quality_score']
                }
            )
            
            logger.info(
                f"Successfully switched provider: {old_provider} -> {new_provider} "
                f"(context: {context}, strategy: {strategy.value}, time: {total_time:.3f}s)"
            )
            
            return result
            
        except Exception as e:
            total_time = time.time() - switch_start
            logger.error(f"Provider switch failed: {e}")
            
            return SwitchResult(
                switch_id=switch_id,
                success=False,
                old_provider=old_provider,
                new_provider=new_provider,
                trigger=trigger,
                strategy=strategy,
                switch_time=0.0,
                total_time=total_time,
                error_message=str(e)
            )
    
    async def _prepare_graceful_switch(
        self,
        context: str,
        old_provider: Optional[str],
        new_provider: str
    ) -> None:
        """Prepare for a graceful provider switch."""
        # Wait for active requests to complete
        switch_context = self._get_or_create_switch_context(context)
        
        # Give existing requests time to complete
        await asyncio.sleep(0.1)
        
        # Drain any pending requests
        if old_provider:
            await self._drain_provider_requests(old_provider)
    
    async def _prepare_predictive_switch(
        self,
        context: str,
        old_provider: Optional[str],
        new_provider: str
    ) -> None:
        """Prepare for a predictive provider switch."""
        # Pre-warm the new provider
        await self._warmup_provider(new_provider)
        
        # Pre-cache models if needed
        await self._precache_models(new_provider, context)
    
    async def _preserve_context(
        self,
        context: str,
        old_provider: Optional[str],
        new_provider: str
    ) -> bool:
        """Preserve context during provider switch."""
        try:
            switch_context = self._get_or_create_switch_context(context)
            
            # Create context bridge if needed
            if old_provider and new_provider:
                context_bridge = self._fallback_manager._create_context_bridge(
                    old_provider, new_provider, switch_context.capability_requirements
                )
                
                if context_bridge:
                    # Apply context bridging
                    bridged_context = context_bridge.bridge_context(switch_context.user_context)
                    switch_context.user_context = bridged_context
                    switch_context.last_updated = time.time()
            
            return True
            
        except Exception as e:
            logger.error(f"Context preservation failed: {e}")
            return False
    
    async def _verify_capability_preservation(
        self,
        context: str,
        old_provider: Optional[str],
        new_provider: str
    ) -> bool:
        """Verify that capabilities are preserved during switch."""
        try:
            switch_context = self._get_or_create_switch_context(context)
            required_capabilities = switch_context.capability_requirements
            
            # Get new provider capabilities
            new_provider_info = self._provider_registry.get_provider_info(new_provider)
            if not new_provider_info:
                return False
            
            new_capabilities = set()
            for model in new_provider_info.base_registration.models:
                new_capabilities.update(model.capabilities)
            
            # Check if all required capabilities are available
            missing_capabilities = required_capabilities - new_capabilities
            
            if missing_capabilities:
                logger.warning(
                    f"Missing capabilities after switch: {missing_capabilities}"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Capability verification failed: {e}")
            return False
    
    async def _execute_switch(self, context: str, new_provider: str) -> float:
        """Execute the actual provider switch."""
        switch_start = time.time()
        
        try:
            # Get provider instance
            provider = self._provider_registry.get_provider(new_provider)
            if not provider:
                raise Exception(f"Provider {new_provider} not available")
            
            # Initialize provider if needed
            if hasattr(provider, 'initialize'):
                await provider.initialize()
            
            # Update any active sessions
            await self._update_active_sessions(context, new_provider)
            
            return time.time() - switch_start
            
        except Exception as e:
            logger.error(f"Switch execution failed: {e}")
            raise
    
    async def _calculate_performance_impact(
        self,
        context: str,
        old_provider: Optional[str],
        new_provider: str
    ) -> float:
        """Calculate performance impact of the switch."""
        try:
            # Get provider metrics
            if old_provider:
                old_metrics = self._provider_registry.get_provider_metrics(old_provider)
                old_latency = old_metrics.average_latency if old_metrics else 0.0
            else:
                old_latency = 0.0
            
            new_metrics = self._provider_registry.get_provider_metrics(new_provider)
            new_latency = new_metrics.average_latency if new_metrics else 0.0
            
            # Calculate impact (positive = improvement, negative = degradation)
            impact = old_latency - new_latency
            
            return impact
            
        except Exception as e:
            logger.error(f"Performance impact calculation failed: {e}")
            return 0.0
    
    async def _drain_provider_requests(self, provider_name: str) -> None:
        """Drain active requests from a provider."""
        # This is a placeholder implementation
        # In a real system, this would coordinate with the provider
        # to complete in-flight requests before switching
        await asyncio.sleep(0.1)
    
    async def _warmup_provider(self, provider_name: str) -> None:
        """Warm up a provider before switching."""
        # This is a placeholder implementation
        # In a real system, this would initialize the provider
        # and potentially make a warm-up request
        pass
    
    async def _precache_models(self, provider_name: str, context: str) -> None:
        """Pre-cache models for a provider."""
        try:
            # Get provider info
            provider_info = self._provider_registry.get_provider_info(provider_name)
            if not provider_info:
                return
            
            # Get context requirements
            switch_context = self._get_or_create_switch_context(context)
            required_capabilities = switch_context.capability_requirements
            
            # Find models that match requirements
            for model in provider_info.base_registration.models:
                if any(cap in model.capabilities for cap in required_capabilities):
                    # Queue model for preloading
                    await self._model_cache.preload_model(provider_name, model.name)
            
        except Exception as e:
            logger.error(f"Model precaching failed: {e}")
    
    async def _update_active_sessions(self, context: str, new_provider: str) -> None:
        """Update active sessions with new provider."""
        # This is a placeholder implementation
        # In a real system, this would update any active sessions
        # to use the new provider
        pass
    
    def _get_or_create_switch_context(self, context: str) -> SwitchContext:
        """Get or create switch context for a context."""
        with self._lock:
            if context not in self._switch_contexts:
                self._switch_contexts[context] = SwitchContext(
                    session_id=f"{context}_{int(time.time())}"
                )
            
            # Update last accessed
            self._switch_contexts[context].last_updated = time.time()
            
            return self._switch_contexts[context]
    
    def _map_context_to_request_context(self, context: str) -> RequestContext:
        """Map switch context to request context."""
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
    
    def _setup_default_triggers(self) -> None:
        """Setup default switch triggers."""
        # Network change trigger
        network_trigger = SwitchTrigger(
            trigger_type=SwitchTriggerType.NETWORK_CHANGE,
            threshold=0.0,
            conditions={'immediate_switch': True},
            cooldown_period=30.0
        )
        self._switch_triggers.append(network_trigger)
        
        # Health degradation trigger
        health_trigger = SwitchTrigger(
            trigger_type=SwitchTriggerType.HEALTH_DEGRADATION,
            threshold=self.config.health_threshold,
            conditions={'min_consecutive_failures': 2},
            cooldown_period=60.0
        )
        self._switch_triggers.append(health_trigger)
        
        # Performance degradation trigger
        performance_trigger = SwitchTrigger(
            trigger_type=SwitchTriggerType.PERFORMANCE_DEGRADATION,
            threshold=self.config.performance_threshold,
            conditions={'min_latency_samples': 5},
            cooldown_period=120.0
        )
        self._switch_triggers.append(performance_trigger)
        
        # Setup trigger handlers
        self._trigger_handlers: Dict[SwitchTriggerType, Callable] = {
            SwitchTriggerType.NETWORK_CHANGE: self._handle_network_trigger,
            SwitchTriggerType.HEALTH_DEGRADATION: self._handle_health_trigger,
            SwitchTriggerType.PERFORMANCE_DEGRADATION: self._handle_performance_trigger,
            SwitchTriggerType.PREDICTIVE_FAILURE: self._handle_predictive_trigger,
            SwitchTriggerType.COST_OPTIMIZATION: self._handle_cost_trigger,
            SwitchTriggerType.CAPABILITY_MISMATCH: self._handle_capability_trigger
        }
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop for intelligent switching."""
        logger.info("Provider switcher monitoring loop started")
        
        while self._monitoring_active:
            try:
                # Check all registered triggers
                await self._check_triggers()
                
                # Update network state
                await self._update_network_state()
                
                # Sleep before next check
                await asyncio.sleep(5.0)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)
        
        logger.info("Provider switcher monitoring loop stopped")
    
    async def _check_triggers(self) -> None:
        """Check all registered triggers for switch conditions."""
        if not self.config.enable_automatic_switching:
            return
        
        for trigger in self._switch_triggers:
            if not trigger.enabled:
                continue
            
            try:
                # Check if trigger conditions are met
                should_switch, context, reason = await self._evaluate_trigger(trigger)
                
                if should_switch:
                    logger.info(f"Trigger activated: {trigger.trigger_type.name} - {reason}")
                    
                    # Get handler for trigger type
                    handler = self._trigger_handlers.get(trigger.trigger_type)
                    if handler:
                        await handler(trigger, context, reason)
                    
            except Exception as e:
                logger.error(f"Error evaluating trigger {trigger.trigger_type.name}: {e}")
    
    async def _evaluate_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate if a trigger should activate."""
        current_time = time.time()
        
        # Check cooldown
        last_trigger_time = self._last_switch_times.get(trigger.trigger_type.name, 0.0)
        if current_time - last_trigger_time < trigger.cooldown_period:
            return False, None, "Trigger in cooldown period"
        
        # Evaluate based on trigger type
        if trigger.trigger_type == SwitchTriggerType.NETWORK_CHANGE:
            return await self._evaluate_network_trigger(trigger)
        elif trigger.trigger_type == SwitchTriggerType.HEALTH_DEGRADATION:
            return await self._evaluate_health_trigger(trigger)
        elif trigger.trigger_type == SwitchTriggerType.PERFORMANCE_DEGRADATION:
            return await self._evaluate_performance_trigger(trigger)
        elif trigger.trigger_type == SwitchTriggerType.PREDICTIVE_FAILURE:
            return await self._evaluate_predictive_trigger(trigger)
        elif trigger.trigger_type == SwitchTriggerType.COST_OPTIMIZATION:
            return await self._evaluate_cost_trigger(trigger)
        elif trigger.trigger_type == SwitchTriggerType.CAPABILITY_MISMATCH:
            return await self._evaluate_capability_trigger(trigger)
        
        return False, None, "Unknown trigger type"
    
    async def _evaluate_network_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate network change trigger."""
        network_status = self._network_monitor.get_current_status()
        
        # Check if network status changed significantly
        if network_status != self._network_state['status']:
            self._network_state['status'] = network_status
            self._network_state['last_change'] = time.time()
            
            # Determine context based on network status
            if network_status == NetworkStatus.OFFLINE:
                return True, "default", "Network went offline"
            elif network_status == NetworkStatus.DEGRADED:
                return True, "default", "Network quality degraded"
            elif network_status == NetworkStatus.ONLINE:
                return True, "default", "Network restored"
        
        return False, None, "No significant network change"
    
    async def _evaluate_health_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate health degradation trigger."""
        health_summary = self._health_monitor.get_health_summary()
        overall_score = health_summary.get('overall_score', 1.0)
        
        if overall_score < trigger.threshold:
            # Find context with most affected provider
            components = health_summary.get('components', {})
            for component_name, component_data in components.items():
                if component_data.get('score', 1.0) < trigger.threshold:
                    return True, component_name.lower(), f"Health degraded: {overall_score:.3f}"
        
        return False, None, f"Health score acceptable: {overall_score:.3f}"
    
    async def _evaluate_performance_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate performance degradation trigger."""
        provider_metrics = self._provider_registry.get_all_provider_metrics()
        
        for provider_name, metrics in provider_metrics.items():
            if metrics.average_latency > trigger.threshold:
                # Find context using this provider
                for context, current_provider in self._decision_maker._current_providers.items():
                    if current_provider == provider_name:
                        return True, context, f"Performance degraded: {metrics.average_latency:.3f}s"
        
        return False, None, "Performance acceptable"
    
    async def _evaluate_predictive_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate predictive failure trigger."""
        if not self.config.enable_predictive_switching:
            return False, None, "Predictive switching disabled"
        
        # Get health trends
        health_summary = self._health_monitor.get_health_summary()
        trends = health_summary.get('trends', {})
        
        for component, trend_data in trends.items():
            direction = trend_data.get('direction', 'stable')
            confidence = trend_data.get('confidence', 0.0)
            
            if (direction == 'degrading' and 
                confidence > self.config.prediction_confidence_threshold):
                return True, component.lower(), f"Predictive failure: {direction} with confidence {confidence}"
        
        return False, None, "No predictive indicators"
    
    async def _evaluate_cost_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate cost optimization trigger."""
        if not self.config.cost_optimization_enabled:
            return False, None, "Cost optimization disabled"
        
        # Check for better cost options
        for context, current_provider in self._decision_maker._current_providers.items():
            optimal_provider = await self._select_optimal_provider(
                context, SwitchStrategy.OPPORTUNISTIC
            )
            
            if optimal_provider and optimal_provider != current_provider:
                return True, context, f"Cost optimization opportunity: {current_provider} -> {optimal_provider}"
        
        return False, None, "No cost optimization opportunities"
    
    async def _evaluate_capability_trigger(
        self,
        trigger: SwitchTrigger
    ) -> Tuple[bool, Optional[str], str]:
        """Evaluate capability mismatch trigger."""
        for context, switch_context in self._switch_contexts.items():
            if not switch_context.capability_requirements:
                continue
            
            current_provider = self._decision_maker.get_current_provider(context)
            if not current_provider:
                continue
            
            # Check if current provider meets requirements
            provider_info = self._provider_registry.get_provider_info(current_provider)
            if not provider_info:
                return True, context, f"Current provider {current_provider} not available"
            
            current_capabilities = set()
            for model in provider_info.base_registration.models:
                current_capabilities.update(model.capabilities)
            
            missing_capabilities = switch_context.capability_requirements - current_capabilities
            if missing_capabilities:
                return True, context, f"Missing capabilities: {missing_capabilities}"
        
        return False, None, "All capability requirements met"
    
    async def _handle_network_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle network change trigger."""
        network_status = self._network_monitor.get_current_status()
        
        if network_status == NetworkStatus.OFFLINE:
            # Switch to offline-capable provider
            strategy = SwitchStrategy.IMMEDIATE
        elif network_status == NetworkStatus.DEGRADED:
            # Switch to more reliable provider
            strategy = SwitchStrategy.GRACEFUL
        else:  # ONLINE
            # Switch back to optimal provider
            strategy = SwitchStrategy.OPPORTUNISTIC
        
        await self.switch_provider(context, strategy=strategy, trigger=trigger, reason=reason)
    
    async def _handle_health_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle health degradation trigger."""
        await self.switch_provider(
            context, strategy=SwitchStrategy.GRACEFUL,
            trigger=trigger, reason=reason
        )
    
    async def _handle_performance_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle performance degradation trigger."""
        await self.switch_provider(
            context, strategy=SwitchStrategy.GRACEFUL,
            trigger=trigger, reason=reason
        )
    
    async def _handle_predictive_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle predictive failure trigger."""
        await self.switch_provider(
            context, strategy=SwitchStrategy.PREDICTIVE,
            trigger=trigger, reason=reason
        )
    
    async def _handle_cost_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle cost optimization trigger."""
        await self.switch_provider(
            context, strategy=SwitchStrategy.OPPORTUNISTIC,
            trigger=trigger, reason=reason
        )
    
    async def _handle_capability_trigger(
        self,
        trigger: SwitchTrigger,
        context: str,
        reason: str
    ) -> None:
        """Handle capability mismatch trigger."""
        await self.switch_provider(
            context, strategy=SwitchStrategy.IMMEDIATE,
            trigger=trigger, reason=reason
        )
    
    async def _update_network_state(self) -> None:
        """Update network state tracking."""
        try:
            network_status = self._network_monitor.get_current_status()
            network_metrics = self._network_monitor.get_network_metrics()
            
            # Update quality score based on metrics
            if network_metrics:
                uptime_percentage = network_metrics.get('uptime_percentage', 100)
                uptime = float(uptime_percentage if isinstance(uptime_percentage, (int, float)) else 100) / 100.0
                avg_response = network_metrics.get('average_response_time', 0.0)
                
                # Calculate quality score (0.0 to 1.0)
                avg_response_value = avg_response if isinstance(avg_response, (int, float)) else 0
                avg_response = float(avg_response_value)
                quality_score = uptime * 0.7 + (1.0 - min(avg_response / 5.0, 1.0)) * 0.3
                
                self._network_state['quality_score'] = quality_score
                self._network_state['bandwidth_estimate'] = network_metrics.get('bandwidth_estimate', 0.0)
                self._network_state['latency_estimate'] = avg_response
            
        except Exception as e:
            logger.error(f"Error updating network state: {e}")
    
    async def _on_network_status_change(
        self,
        old_status: NetworkStatus,
        new_status: NetworkStatus
    ) -> None:
        """Handle network status changes."""
        logger.info(f"Network status change detected: {old_status.value} -> {new_status.value}")
        
        # Update network state
        self._network_state['status'] = new_status
        self._network_state['last_change'] = time.time()
        
        # Trigger network change evaluation
        if self.config.enable_automatic_switching:
            for trigger in self._switch_triggers:
                if trigger.trigger_type == SwitchTriggerType.NETWORK_CHANGE:
                    should_switch, context, reason = await self._evaluate_trigger(trigger)
                    if should_switch and context:
                        await self._handle_network_trigger(trigger, context, reason)
    
    async def _optimization_loop(self) -> None:
        """Background optimization loop."""
        logger.info("Provider switcher optimization loop started")
        
        while self._monitoring_active:
            try:
                await self._optimize_switching()
                await asyncio.sleep(self.config.optimization_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Provider switcher optimization loop stopped")
    
    async def _optimize_switching(self) -> None:
        """Optimize switching based on historical data."""
        try:
            if len(self._switch_history) < 10:
                return  # Not enough data for optimization
            
            # Analyze switch patterns
            switch_patterns = self._analyze_switch_patterns()
            
            # Optimize trigger thresholds
            await self._optimize_trigger_thresholds(switch_patterns)
            
            # Optimize strategy selection
            await self._optimize_strategy_selection(switch_patterns)
            
        except Exception as e:
            logger.error(f"Error optimizing switching: {e}")
    
    def _analyze_switch_patterns(self) -> Dict[str, Any]:
        """Analyze historical switch patterns."""
        patterns = {
            'trigger_frequency': defaultdict(int),
            'strategy_effectiveness': defaultdict(list),
            'context_switch_frequency': defaultdict(int),
            'time_based_patterns': defaultdict(list),
            'performance_impacts': []
        }
        
        for result in self._switch_history:
            # Trigger frequency
            patterns['trigger_frequency'][result.trigger.name] += 1
            
            # Strategy effectiveness
            patterns['strategy_effectiveness'][result.strategy.value].append(
                1.0 if result.success else 0.0
            )
            
            # Context switch frequency
            context = result.metadata.get('context', 'unknown')
            patterns['context_switch_frequency'][context] += 1
            
            # Time-based patterns
            hour = datetime.fromtimestamp(result.timestamp).hour
            patterns['time_based_patterns'][hour].append(result.success)
            
            # Performance impacts
            if result.performance_impact != 0:
                patterns['performance_impacts'].append(result.performance_impact)
        
        return patterns
    
    async def _optimize_trigger_thresholds(self, patterns: Dict[str, Any]) -> None:
        """Optimize trigger thresholds based on patterns."""
        # This is a placeholder for threshold optimization
        # In a real implementation, this would adjust thresholds
        # based on false positive/negative rates
        pass
    
    async def _optimize_strategy_selection(self, patterns: Dict[str, Any]) -> None:
        """Optimize strategy selection based on patterns."""
        # This is a placeholder for strategy optimization
        # In a real implementation, this would learn which strategies
        # work best in different situations
        pass
    
    def _record_switch(self, result: SwitchResult) -> None:
        """Record a switch result for analytics."""
        with self._lock:
            # Add to history
            self._switch_history.append(result)
            
            # Update metrics
            self._metrics.total_switches += 1
            
            if result.success:
                self._metrics.successful_switches += 1
            else:
                self._metrics.failed_switches += 1
            
            # Update average switch time
            if result.switch_time > 0:
                self._metrics.average_switch_time = (
                    (self._metrics.average_switch_time * (self._metrics.total_switches - 1) + 
                     result.switch_time) / self._metrics.total_switches
                )
            
            # Update preservation rates
            if result.context_preserved:
                preservation_count = self._metrics.context_preservation_rate * (self._metrics.total_switches - 1) + 1
                self._metrics.context_preservation_rate = preservation_count / self._metrics.total_switches
            
            if result.capabilities_preserved:
                preservation_count = self._metrics.capability_preservation_rate * (self._metrics.total_switches - 1) + 1
                self._metrics.capability_preservation_rate = preservation_count / self._metrics.total_switches
            
            # Update frequency counts
            context = result.metadata.get('context', 'unknown')
            self._metrics.switch_frequency[context] = self._metrics.switch_frequency.get(context, 0) + 1
            self._metrics.trigger_frequency[result.trigger] = self._metrics.trigger_frequency.get(result.trigger, 0) + 1
            
            # Update performance impacts
            if result.performance_impact != 0:
                self._metrics.performance_impacts.append(result.performance_impact)
            
            self._metrics.last_updated = time.time()
    
    def get_switch_metrics(self) -> SwitchMetrics:
        """Get current switch metrics."""
        with self._lock:
            return self._metrics
    
    def get_switch_history(self, limit: int = 50) -> List[SwitchResult]:
        """Get recent switch history."""
        with self._lock:
            return list(self._switch_history)[-limit:]
    
    def get_switch_analytics(self) -> Dict[str, Any]:
        """Get comprehensive switch analytics."""
        with self._lock:
            # Calculate success rate
            success_rate = (
                self._metrics.successful_switches / 
                max(self._metrics.total_switches, 1)
            )
            
            # Calculate average performance impact
            avg_performance_impact = (
                sum(self._metrics.performance_impacts) / 
                max(len(self._metrics.performance_impacts), 1)
            )
            
            # Get most common triggers
            common_triggers = sorted(
                self._metrics.trigger_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            # Get most switched contexts
            common_contexts = sorted(
                self._metrics.switch_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            return {
                'total_switches': self._metrics.total_switches,
                'success_rate': success_rate,
                'average_switch_time': self._metrics.average_switch_time,
                'context_preservation_rate': self._metrics.context_preservation_rate,
                'capability_preservation_rate': self._metrics.capability_preservation_rate,
                'average_performance_impact': avg_performance_impact,
                'common_triggers': [
                    {'trigger': trigger.name, 'count': count}
                    for trigger, count in common_triggers
                ],
                'common_contexts': [
                    {'context': context, 'count': count}
                    for context, count in common_contexts
                ],
                'network_state': self._network_state,
                'active_switches': len(self._active_switches),
                'last_updated': self._metrics.last_updated
            }
    
    def update_context_requirements(
        self,
        context: str,
        capabilities: Set[str],
        performance_constraints: Optional[Dict[str, float]] = None,
        cost_constraints: Optional[Dict[str, float]] = None
    ) -> None:
        """Update context requirements for intelligent switching."""
        switch_context = self._get_or_create_switch_context(context)
        
        switch_context.capability_requirements = capabilities
        
        if performance_constraints:
            switch_context.performance_constraints.update(performance_constraints)
        
        if cost_constraints:
            switch_context.cost_constraints.update(cost_constraints)
        
        switch_context.last_updated = time.time()
        
        logger.info(f"Updated context requirements for {context}: {capabilities}")
    
    def clear_context_cache(self, context: Optional[str] = None) -> None:
        """Clear switch context cache."""
        with self._lock:
            if context:
                self._switch_contexts.pop(context, None)
                logger.info(f"Cleared switch context for {context}")
            else:
                self._switch_contexts.clear()
                logger.info("Cleared all switch contexts")


# Global instance
_intelligent_provider_switcher: Optional[IntelligentProviderSwitcher] = None
_switcher_lock = threading.RLock()


def get_intelligent_provider_switcher(config: Optional[SwitchConfig] = None) -> IntelligentProviderSwitcher:
    """Get or create global intelligent provider switcher instance."""
    global _intelligent_provider_switcher
    if _intelligent_provider_switcher is None:
        with _switcher_lock:
            if _intelligent_provider_switcher is None:
                _intelligent_provider_switcher = IntelligentProviderSwitcher(config)
    return _intelligent_provider_switcher


async def initialize_intelligent_provider_switcher(config: Optional[SwitchConfig] = None) -> IntelligentProviderSwitcher:
    """Initialize intelligent provider switcher system."""
    switcher = get_intelligent_provider_switcher(config)
    await switcher.start_monitoring()
    logger.info("Intelligent provider switcher system initialized")
    return switcher


# Export main classes for easy import
__all__ = [
    "SwitchStrategy",
    "SwitchTrigger",
    "SwitchResult",
    "SwitchContext",
    "SwitchMetrics",
    "SwitchConfig",
    "IntelligentProviderSwitcher",
    "get_intelligent_provider_switcher",
    "initialize_intelligent_provider_switcher",
]