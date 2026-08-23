"""
Reasoning Preservation Layer

This layer ensures that existing reasoning logic (DecisionEngine, orchestration runtime, 
lightweight model scaffolding, etc.) is preserved while adding intelligent model routing
and optimization capabilities.

Requirements implemented: 8.1, 8.2, 8.3, 8.4
"""

import asyncio
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Union
from enum import Enum
import weakref
import inspect

from ai_karen_engine.core.model_runtime.routing.intelligent_model_router import (
    ModelRouter, RoutingDecision, get_model_router
)
from ai_karen_engine.core.model_runtime.management.model_connection_manager import (
    ModelConnectionManager, get_connection_manager
)
from ai_karen_engine.core.model_runtime.recommendation.model_recommendation_engine import (
    ModelRecommendationEngine, get_recommendation_engine
)
from ai_karen_engine.core.model_runtime.model_discovery_service import get_model_discovery_service
from ai_karen_engine.services.database.cache.smart_cache_manager import get_smart_cache_manager
from ai_karen_engine.services.formatting.response_performance_metrics import (
    get_performance_metrics_service,
)
from ai_karen_engine.services.optimization.intelligent_scaffolding_service import (
    get_intelligent_scaffolding_service,
)

logger = logging.getLogger("kari.reasoning_preservation_layer")

class ReasoningComponent(Enum):
    """Types of reasoning components to preserve."""
    DECISION_ENGINE = "decision_engine"
    FLOW_MANAGER = "flow_manager"
    SCAFFOLDING_SERVICE = "scaffolding_service"  # Renamed from model-specific scaffolding
    PROFILE_MANAGER = "profile_manager"
    INTENT_ANALYSIS = "intent_analysis"
    MEMORY_INTEGRATION = "memory_integration"
    PERSONALITY_APPLICATION = "personality_application"

@dataclass
class ReasoningContext:
    """Context for reasoning operations."""
    session_id: str
    component: ReasoningComponent
    operation: str
    input_data: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

@dataclass
class ReasoningResult:
    """Result from reasoning operations."""
    success: bool
    result: Any
    component: ReasoningComponent
    operation: str
    execution_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

class ReasoningPreservationLayer:
    """
    Preservation layer that wraps existing reasoning components without modifying them.
    
    This layer acts as a transparent proxy that:
    - Preserves all existing reasoning logic and decision-making
    - Adds intelligent model routing capabilities
    - Provides performance optimization without disrupting flows
    - Maintains compatibility with existing APIs
    - Tracks reasoning operations for optimization
    """
    
    def __init__(self):
        self.model_router = get_model_router()
        self.connection_manager = get_connection_manager(self.model_router)
        self.recommendation_engine = get_recommendation_engine(self.model_router)
        
        # Integration with optimization services
        try:
            self.model_discovery_engine = get_model_discovery_service()
        except Exception as e:
            logger.warning(f"Model discovery engine not available: {e}")
            self.model_discovery_engine = None
            
        try:
            self.smart_cache_manager = get_smart_cache_manager()
        except Exception as e:
            logger.warning(f"Smart cache manager not available: {e}")
            self.smart_cache_manager = None
            
        try:
            self.performance_metrics_service = get_performance_metrics_service()
        except Exception as e:
            logger.warning(f"Performance metrics service not available: {e}")
            self.performance_metrics_service = None
        
        # Component registry
        self.wrapped_components: Dict[str, Any] = {}
        self.component_callbacks: Dict[ReasoningComponent, List[Callable]] = {}
        self.reasoning_sessions: Dict[str, ReasoningContext] = {}
        
        # Performance tracking
        self.operation_metrics: Dict[str, List[float]] = {}
        self.reasoning_statistics: Dict[str, Any] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Preservation flags
        self.preserve_decision_engine = True
        self.preserve_flow_manager = True
        self.preserve_scaffolding_service = True
        self.preserve_profile_routing = True
        self.preserve_memory_integration = True
        self.preserve_personality_application = True
        
        logger.info("Reasoning Preservation Layer initialized with optimization integrations")
    
    def wrap_decision_engine(self, decision_engine: Any) -> Any:
        """
        Wrap existing DecisionEngine with optimization layer.
        
        This method creates a transparent wrapper that preserves all existing
        decision-making logic while adding intelligent model routing capabilities.
        """
        if not self.preserve_decision_engine:
            return decision_engine
        
        try:
            # Create wrapper class dynamically
            wrapper_class = self._create_component_wrapper(
                decision_engine.__class__,
                ReasoningComponent.DECISION_ENGINE
            )
            
            # Create wrapper instance
            wrapper = wrapper_class(decision_engine, self)
            
            # Register component
            self.wrapped_components["decision_engine"] = wrapper
            
            logger.info("DecisionEngine wrapped with preservation layer")
            return wrapper
            
        except Exception as e:
            logger.error(f"Failed to wrap DecisionEngine: {e}")
            return decision_engine
    
    def wrap_flow_manager(self, flow_manager: Any) -> Any:
        """
        Wrap the existing orchestration runtime while maintaining workflow execution.
        
        Preserves flow execution and statistics while adding performance monitoring.
        """
        if not self.preserve_flow_manager:
            return flow_manager
        
        try:
            wrapper_class = self._create_component_wrapper(
                flow_manager.__class__,
                ReasoningComponent.FLOW_MANAGER
            )
            
            wrapper = wrapper_class(flow_manager, self)
            self.wrapped_components["flow_manager"] = wrapper
            
            logger.info("Orchestration runtime wrapped with preservation layer")
            return wrapper
            
        except Exception as e:
            logger.error(f"Failed to wrap orchestration runtime: {e}")
            return flow_manager
    
    def wrap_scaffolding_service(self, scaffolding_service: Any) -> Any:
        """
        Wrap scaffolding service while preserving reasoning scaffolding functionality.
        
        This now works with the intelligent scaffolding service.
        Maintains fast reasoning scaffolding and outline generation capabilities through
        intelligent model selection rather than a hardcoded model.
        """
        if not self.preserve_scaffolding_service:
            return scaffolding_service
        
        try:
            wrapper_class = self._create_component_wrapper(
                scaffolding_service.__class__,
                ReasoningComponent.SCAFFOLDING_SERVICE
            )
            
            wrapper = wrapper_class(scaffolding_service, self)
            self.wrapped_components["scaffolding_service"] = wrapper
            
            logger.info("Scaffolding service wrapped with preservation layer")
            return wrapper
            
        except Exception as e:
            logger.error(f"Failed to wrap scaffolding service: {e}")
            return scaffolding_service
    
    def wrap_profile_manager(self, profile_manager: Any) -> Any:
        """
        Wrap ProfileManager while maintaining profile-based model routing.
        
        Preserves existing profile routing for different task types while
        enhancing with discovered models.
        """
        if not self.preserve_profile_routing:
            return profile_manager
        
        try:
            wrapper_class = self._create_component_wrapper(
                profile_manager.__class__,
                ReasoningComponent.PROFILE_MANAGER
            )
            
            wrapper = wrapper_class(profile_manager, self)
            self.wrapped_components["profile_manager"] = wrapper
            
            logger.info("ProfileManager wrapped with preservation layer")
            return wrapper
            
        except Exception as e:
            logger.error(f"Failed to wrap ProfileManager: {e}")
            return profile_manager
    
    def _create_component_wrapper(self, original_class: type, component_type: ReasoningComponent) -> type:
        """
        Dynamically create a wrapper class that preserves original functionality.
        
        The wrapper intercepts method calls to add optimization capabilities
        while ensuring all original behavior is preserved.
        """
        class ComponentWrapper:
            def __init__(self, wrapped_instance, preservation_layer):
                self._wrapped = wrapped_instance
                self._preservation_layer = preservation_layer
                self._component_type = component_type
                
                # Copy all attributes from wrapped instance
                for attr_name in dir(wrapped_instance):
                    if not attr_name.startswith('_'):
                        try:
                            attr_value = getattr(wrapped_instance, attr_name)
                            if not callable(attr_value):
                                setattr(self, attr_name, attr_value)
                        except Exception:
                            pass  # Skip problematic attributes
            
            def __getattr__(self, name):
                """Intercept method calls to add preservation logic."""
                attr = getattr(self._wrapped, name)
                
                if callable(attr):
                    return self._wrap_method(name, attr)
                else:
                    return attr
            
            def _wrap_method(self, method_name: str, original_method: Callable):
                """Wrap a method with preservation logic."""
                async def async_wrapper(*args, **kwargs):
                    return await self._execute_with_preservation(
                        method_name, original_method, args, kwargs, is_async=True
                    )
                
                def sync_wrapper(*args, **kwargs):
                    return self._execute_with_preservation_sync(
                        method_name, original_method, args, kwargs
                    )
                
                # Return appropriate wrapper based on method type
                if inspect.iscoroutinefunction(original_method):
                    return async_wrapper
                else:
                    return sync_wrapper
            
            async def _execute_with_preservation(
                self, 
                method_name: str, 
                original_method: Callable, 
                args: tuple, 
                kwargs: dict,
                is_async: bool = False
            ):
                """Execute method with preservation logic."""
                start_time = time.time()
                session_id = kwargs.get('session_id') or f"session_{int(time.time())}"
                
                # Create reasoning context
                context = ReasoningContext(
                    session_id=session_id,
                    component=self._component_type,
                    operation=method_name,
                    input_data={"args": args, "kwargs": kwargs}
                )
                
                try:
                    # Pre-execution hooks
                    await self._preservation_layer._pre_execution_hook(context)
                    
                    # Execute original method
                    if is_async:
                        result = await original_method(*args, **kwargs)
                    else:
                        result = original_method(*args, **kwargs)
                    
                    # Post-execution hooks
                    execution_time = time.time() - start_time
                    reasoning_result = ReasoningResult(
                        success=True,
                        result=result,
                        component=self._component_type,
                        operation=method_name,
                        execution_time=execution_time
                    )
                    
                    await self._preservation_layer._post_execution_hook(context, reasoning_result)
                    
                    return result
                    
                except Exception as e:
                    # Error handling with preservation
                    execution_time = time.time() - start_time
                    reasoning_result = ReasoningResult(
                        success=False,
                        result=None,
                        component=self._component_type,
                        operation=method_name,
                        execution_time=execution_time,
                        error=str(e)
                    )
                    
                    await self._preservation_layer._error_handling_hook(context, reasoning_result, e)
                    
                    # Re-raise original exception to preserve behavior
                    raise
            
            def _execute_with_preservation_sync(
                self, 
                method_name: str, 
                original_method: Callable, 
                args: tuple, 
                kwargs: dict
            ):
                """Synchronous version of preservation execution."""
                start_time = time.time()
                session_id = kwargs.get('session_id') or f"session_{int(time.time())}"
                
                context = ReasoningContext(
                    session_id=session_id,
                    component=self._component_type,
                    operation=method_name,
                    input_data={"args": args, "kwargs": kwargs}
                )
                
                try:
                    # Pre-execution (sync)
                    self._preservation_layer._pre_execution_hook_sync(context)
                    
                    # Execute original method
                    result = original_method(*args, **kwargs)
                    
                    # Post-execution (sync)
                    execution_time = time.time() - start_time
                    reasoning_result = ReasoningResult(
                        success=True,
                        result=result,
                        component=self._component_type,
                        operation=method_name,
                        execution_time=execution_time
                    )
                    
                    self._preservation_layer._post_execution_hook_sync(context, reasoning_result)
                    
                    return result
                    
                except Exception as e:
                    execution_time = time.time() - start_time
                    reasoning_result = ReasoningResult(
                        success=False,
                        result=None,
                        component=self._component_type,
                        operation=method_name,
                        execution_time=execution_time,
                        error=str(e)
                    )
                    
                    self._preservation_layer._error_handling_hook_sync(context, reasoning_result, e)
                    raise
        
        # Set class name for debugging
        ComponentWrapper.__name__ = f"Wrapped{original_class.__name__}"
        ComponentWrapper.__qualname__ = f"Wrapped{original_class.__qualname__}"
        
        return ComponentWrapper
    
    async def _pre_execution_hook(self, context: ReasoningContext):
        """Hook executed before reasoning operations."""
        try:
            # Store reasoning context
            with self._lock:
                self.reasoning_sessions[context.session_id] = context
            
            # Execute component-specific pre-hooks
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if inspect.iscoroutinefunction(callback):
                        await callback("pre_execution", context)
                    else:
                        callback("pre_execution", context)
                except Exception as e:
                    logger.error(f"Pre-execution callback failed: {e}")
            
            # Optimize model selection if needed
            await self._optimize_model_selection(context)
            
        except Exception as e:
            logger.error(f"Pre-execution hook failed: {e}")
    
    def _pre_execution_hook_sync(self, context: ReasoningContext):
        """Synchronous version of pre-execution hook."""
        try:
            with self._lock:
                self.reasoning_sessions[context.session_id] = context
            
            # Execute sync callbacks only
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if not inspect.iscoroutinefunction(callback):
                        callback("pre_execution", context)
                except Exception as e:
                    logger.error(f"Pre-execution callback failed: {e}")
                    
        except Exception as e:
            logger.error(f"Pre-execution hook failed: {e}")
    
    async def _post_execution_hook(self, context: ReasoningContext, result: ReasoningResult):
        """Hook executed after reasoning operations."""
        try:
            # Update performance metrics
            self._update_performance_metrics(context.operation, result.execution_time)
            
            # Execute component-specific post-hooks
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if inspect.iscoroutinefunction(callback):
                        await callback("post_execution", context, result)
                    else:
                        callback("post_execution", context, result)
                except Exception as e:
                    logger.error(f"Post-execution callback failed: {e}")
            
            # Clean up session if needed
            with self._lock:
                if context.session_id in self.reasoning_sessions:
                    del self.reasoning_sessions[context.session_id]
            
        except Exception as e:
            logger.error(f"Post-execution hook failed: {e}")
    
    def _post_execution_hook_sync(self, context: ReasoningContext, result: ReasoningResult):
        """Synchronous version of post-execution hook."""
        try:
            self._update_performance_metrics(context.operation, result.execution_time)
            
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if not inspect.iscoroutinefunction(callback):
                        callback("post_execution", context, result)
                except Exception as e:
                    logger.error(f"Post-execution callback failed: {e}")
            
            with self._lock:
                if context.session_id in self.reasoning_sessions:
                    del self.reasoning_sessions[context.session_id]
                    
        except Exception as e:
            logger.error(f"Post-execution hook failed: {e}")
    
    async def _error_handling_hook(
        self, 
        context: ReasoningContext, 
        result: ReasoningResult, 
        error: Exception
    ):
        """Hook for handling errors while preserving original behavior."""
        try:
            # Log error for analysis
            logger.error(f"Reasoning operation failed: {context.component.value}.{context.operation}: {error}")
            
            # Update error metrics
            self._update_error_metrics(context.operation, str(error))
            
            # Execute error callbacks
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if inspect.iscoroutinefunction(callback):
                        await callback("error", context, result, error)
                    else:
                        callback("error", context, result, error)
                except Exception as e:
                    logger.error(f"Error callback failed: {e}")
            
        except Exception as e:
            logger.error(f"Error handling hook failed: {e}")
    
    def _error_handling_hook_sync(
        self, 
        context: ReasoningContext, 
        result: ReasoningResult, 
        error: Exception
    ):
        """Synchronous version of error handling hook."""
        try:
            logger.error(f"Reasoning operation failed: {context.component.value}.{context.operation}: {error}")
            self._update_error_metrics(context.operation, str(error))
            
            callbacks = self.component_callbacks.get(context.component, [])
            for callback in callbacks:
                try:
                    if not inspect.iscoroutinefunction(callback):
                        callback("error", context, result, error)
                except Exception as e:
                    logger.error(f"Error callback failed: {e}")
                    
        except Exception as e:
            logger.error(f"Error handling hook failed: {e}")
    
    async def _optimize_model_selection(self, context: ReasoningContext):
        """Optimize model selection for reasoning operations."""
        try:
            # Only optimize if we have model routing capabilities
            if not hasattr(self, 'model_router'):
                return
            
            # Determine if model optimization is beneficial
            if context.component in [ReasoningComponent.DECISION_ENGINE, ReasoningComponent.FLOW_MANAGER]:
                # These components might benefit from model optimization
                operation_data = context.input_data.get("kwargs", {})
                
                # Check if there's a query or task that could benefit from model routing
                query = operation_data.get("query") or operation_data.get("message") or operation_data.get("input")
                
                if query and isinstance(query, str):
                    # Get model recommendations
                    recommendations = await self.recommendation_engine.recommend_models(
                        task_description=query,
                        max_recommendations=3
                    )
                    
                    if recommendations:
                        # Store recommendations in context for potential use
                        context.metadata["model_recommendations"] = [
                            {
                                "model_id": rec.model_id,
                                "score": rec.score,
                                "reasoning": rec.reasoning[:2]  # Top 2 reasons
                            }
                            for rec in recommendations
                        ]
            
        except Exception as e:
            logger.error(f"Model selection optimization failed: {e}")
    
    def _update_performance_metrics(self, operation: str, execution_time: float):
        """Update performance metrics for operations."""
        with self._lock:
            if operation not in self.operation_metrics:
                self.operation_metrics[operation] = []
            
            self.operation_metrics[operation].append(execution_time)
            
            # Keep only recent metrics (last 100 operations)
            if len(self.operation_metrics[operation]) > 100:
                self.operation_metrics[operation] = self.operation_metrics[operation][-100:]
    
    def _update_error_metrics(self, operation: str, error: str):
        """Update error metrics for operations."""
        with self._lock:
            if "errors" not in self.reasoning_statistics:
                self.reasoning_statistics["errors"] = {}
            
            if operation not in self.reasoning_statistics["errors"]:
                self.reasoning_statistics["errors"][operation] = []
            
            self.reasoning_statistics["errors"][operation].append({
                "error": error,
                "timestamp": time.time()
            })
            
            # Keep only recent errors (last 50)
            if len(self.reasoning_statistics["errors"][operation]) > 50:
                self.reasoning_statistics["errors"][operation] = \
                    self.reasoning_statistics["errors"][operation][-50:]
    
    def add_component_callback(self, component: ReasoningComponent, callback: Callable):
        """Add a callback for component operations."""
        if component not in self.component_callbacks:
            self.component_callbacks[component] = []
        
        self.component_callbacks[component].append(callback)
        logger.debug(f"Added callback for {component.value}")
    
    def remove_component_callback(self, component: ReasoningComponent, callback: Callable):
        """Remove a callback for component operations."""
        if component in self.component_callbacks:
            try:
                self.component_callbacks[component].remove(callback)
                logger.debug(f"Removed callback for {component.value}")
            except ValueError:
                pass
    
    def get_reasoning_statistics(self) -> Dict[str, Any]:
        """Get comprehensive reasoning statistics."""
        with self._lock:
            stats = {
                "wrapped_components": list(self.wrapped_components.keys()),
                "active_sessions": len(self.reasoning_sessions),
                "operation_metrics": {},
                "preservation_flags": {
                    "decision_engine": self.preserve_decision_engine,
                    "flow_manager": self.preserve_flow_manager,
                    "scaffolding_service": self.preserve_scaffolding_service,
                    "profile_routing": self.preserve_profile_routing,
                    "memory_integration": self.preserve_memory_integration,
                    "personality_application": self.preserve_personality_application
                },
                "callback_counts": {
                    component.value: len(callbacks)
                    for component, callbacks in self.component_callbacks.items()
                }
            }
            
            # Calculate operation statistics
            for operation, times in self.operation_metrics.items():
                if times:
                    stats["operation_metrics"][operation] = {
                        "count": len(times),
                        "average_time": sum(times) / len(times),
                        "min_time": min(times),
                        "max_time": max(times),
                        "recent_average": sum(times[-10:]) / min(len(times), 10)
                    }
            
            # Add error statistics
            stats.update(self.reasoning_statistics)
            
            return stats
    
    def configure_preservation(self, **flags):
        """Configure preservation flags."""
        if "decision_engine" in flags:
            self.preserve_decision_engine = flags["decision_engine"]
        if "flow_manager" in flags:
            self.preserve_flow_manager = flags["flow_manager"]
        if "scaffolding_service" in flags:
            self.preserve_scaffolding_service = flags["scaffolding_service"]
        if "profile_routing" in flags:
            self.preserve_profile_routing = flags["profile_routing"]
        if "memory_integration" in flags:
            self.preserve_memory_integration = flags["memory_integration"]
        if "personality_application" in flags:
            self.preserve_personality_application = flags["personality_application"]
        
        logger.info(f"Updated preservation configuration: {flags}")

# Global instance
_preservation_layer: Optional[ReasoningPreservationLayer] = None
_layer_lock = threading.RLock()

def get_reasoning_preservation_layer() -> ReasoningPreservationLayer:
    """Get the global reasoning preservation layer instance."""
    global _preservation_layer
    if _preservation_layer is None:
        with _layer_lock:
            if _preservation_layer is None:
                _preservation_layer = ReasoningPreservationLayer()
    return _preservation_layer

def preserve_reasoning_component(component: Any, component_type: ReasoningComponent) -> Any:
    """Convenience function to wrap a reasoning component."""
    layer = get_reasoning_preservation_layer()
    
    if component_type == ReasoningComponent.DECISION_ENGINE:
        return layer.wrap_decision_engine(component)
    elif component_type == ReasoningComponent.FLOW_MANAGER:
        return layer.wrap_flow_manager(component)
    elif component_type == ReasoningComponent.SCAFFOLDING_SERVICE:
        return layer.wrap_scaffolding_service(component)
    elif component_type == ReasoningComponent.PROFILE_MANAGER:
        return layer.wrap_profile_manager(component)
    else:
        logger.warning(f"Unknown component type: {component_type}")
        return component

