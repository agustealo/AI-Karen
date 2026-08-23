"""
Optimization Integration Orchestrator

Main orchestrator that integrates all optimization components with existing
codebase while preserving reasoning logic and existing functionality.

This is the central integration point for task 14.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
from datetime import datetime

# Import all integration components
from ai_karen_engine.services.orchestration.reasoning_preservation_layer import (
    get_reasoning_preservation_layer, ReasoningComponent
)
from ai_karen_engine.core.model_runtime.management.model_management_service import (
    get_integrated_model_manager, initialize_integrated_model_management
)
from ai_karen_engine.services.database.cache.integrated_cache_system import (
    get_integrated_cache_system, initialize_integrated_cache_system
)
from ai_karen_engine.services.monitoring.integrated_performance_monitoring import (
    get_integrated_performance_monitor, initialize_integrated_performance_monitoring
)
from ai_karen_engine.services.optimization.configuration_manager import (
    get_optimization_config_manager, get_optimization_config
)

if TYPE_CHECKING:
    from ai_karen_engine.services.optimization.intelligent_scaffolding_service import (
        IntelligentScaffoldingService,
    )
else:
    IntelligentScaffoldingService = Any
DecisionEngine = Any
OrchestrationRuntime = Any

logger = logging.getLogger("kari.optimization_integration_orchestrator")

@dataclass
class IntegrationStatus:
    """Status of optimization integration."""
    component: str
    integrated: bool = False
    error_message: Optional[str] = None
    integration_time: Optional[datetime] = None

class OptimizationIntegrationOrchestrator:
    """
    Main orchestrator for integrating optimization system with existing codebase
    while preserving all reasoning logic and existing functionality.
    """
    
    def __init__(self):
        self.logger = logging.getLogger("kari.optimization_integration_orchestrator")
        
        # Integration components
        self.reasoning_preservation_layer = get_reasoning_preservation_layer()
        self.model_manager = get_integrated_model_manager()
        self.cache_system = get_integrated_cache_system()
        self.performance_monitor = get_integrated_performance_monitor()
        self.config_manager = get_optimization_config_manager()
        
        # Integration state
        self.integration_status: Dict[str, IntegrationStatus] = {}
        self.integrated_components: Dict[str, Any] = {}
        self.integration_callbacks: List[Callable] = []
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Initialization state
        self._initialized = False
        self._initialization_error: Optional[str] = None
        
        self.logger.info("Optimization Integration Orchestrator created")
    
    async def initialize_integration(self) -> bool:
        """Initialize the complete optimization integration system."""
        if self._initialized:
            return True
        
        try:
            self.logger.info("Starting optimization integration initialization...")
            
            # Get configuration
            config = get_optimization_config()
            
            if not config.enable_optimization_system:
                self.logger.info("Optimization system disabled in configuration")
                return True
            
            # Initialize components in order
            await self._initialize_model_management()
            await self._initialize_cache_system()
            await self._initialize_performance_monitoring()
            await self._setup_configuration_callbacks()
            
            # Mark as initialized
            self._initialized = True
            self.logger.info("Optimization integration initialization completed successfully")
            
            # Notify callbacks
            for callback in self.integration_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback("initialization_complete", True)
                    else:
                        callback("initialization_complete", True)
                except Exception as e:
                    self.logger.error(f"Integration callback failed: {e}")
            
            return True
            
        except Exception as e:
            self._initialization_error = str(e)
            self.logger.error(f"Optimization integration initialization failed: {e}")
            return False
    
    async def _initialize_model_management(self):
        """Initialize integrated model management."""
        try:
            self.logger.info("Initializing integrated model management...")
            
            # Initialize model discovery and integration
            await initialize_integrated_model_management()
            
            self.integration_status["model_management"] = IntegrationStatus(
                component="model_management",
                integrated=True,
                integration_time=datetime.now()
            )
            
            self.logger.info("Integrated model management initialized")
            
        except Exception as e:
            self.integration_status["model_management"] = IntegrationStatus(
                component="model_management",
                integrated=False,
                error_message=str(e)
            )
            raise
    
    async def _initialize_cache_system(self):
        """Initialize integrated cache system."""
        try:
            self.logger.info("Initializing integrated cache system...")
            
            # Initialize cache system
            await initialize_integrated_cache_system()
            
            self.integration_status["cache_system"] = IntegrationStatus(
                component="cache_system",
                integrated=True,
                integration_time=datetime.now()
            )
            
            self.logger.info("Integrated cache system initialized")
            
        except Exception as e:
            self.integration_status["cache_system"] = IntegrationStatus(
                component="cache_system",
                integrated=False,
                error_message=str(e)
            )
            raise
    
    async def _initialize_performance_monitoring(self):
        """Initialize integrated performance monitoring."""
        try:
            self.logger.info("Initializing integrated performance monitoring...")
            
            # Initialize performance monitoring
            await initialize_integrated_performance_monitoring()
            
            self.integration_status["performance_monitoring"] = IntegrationStatus(
                component="performance_monitoring",
                integrated=True,
                integration_time=datetime.now()
            )
            
            self.logger.info("Integrated performance monitoring initialized")
            
        except Exception as e:
            self.integration_status["performance_monitoring"] = IntegrationStatus(
                component="performance_monitoring",
                integrated=False,
                error_message=str(e)
            )
            raise
    
    async def _setup_configuration_callbacks(self):
        """Set up configuration change callbacks."""
        try:
            def config_change_callback(old_config, new_config):
                """Handle configuration changes."""
                try:
                    self.logger.info("Configuration changed, updating integrated components...")
                    
                    # Update reasoning preservation settings
                    self.reasoning_preservation_layer.configure_preservation(
                        decision_engine=new_config.reasoning_preservation.preserve_decision_engine,
                        flow_manager=new_config.reasoning_preservation.preserve_flow_manager,
                        scaffolding_service=new_config.reasoning_preservation.preserve_scaffolding_service,
                        profile_routing=new_config.reasoning_preservation.preserve_profile_routing,
                        memory_integration=new_config.reasoning_preservation.preserve_memory_integration,
                        personality_application=new_config.reasoning_preservation.preserve_personality_application
                    )
                    
                    self.logger.info("Configuration changes applied to integrated components")
                    
                except Exception as e:
                    self.logger.error(f"Failed to apply configuration changes: {e}")
            
            self.config_manager.add_config_callback(config_change_callback)
            
        except Exception as e:
            self.logger.error(f"Failed to setup configuration callbacks: {e}")
    
    async def integrate_reasoning_components(
        self,
        decision_engine: Optional[DecisionEngine] = None,
        orchestration_runtime: Optional[OrchestrationRuntime] = None,
        scaffolding_service: Optional[IntelligentScaffoldingService] = None
    ) -> Dict[str, Any]:
        """
        Integrate reasoning components with optimization while preserving their logic.
        
        This is the main integration method that wraps existing components.
        """
        try:
            integrated_components = {}
            
            # Integrate DecisionEngine
            if decision_engine:
                self.logger.info("Integrating DecisionEngine with optimization...")
                
                # Wrap with reasoning preservation layer
                wrapped_decision_engine = self.reasoning_preservation_layer.wrap_decision_engine(decision_engine)
                
                # Integrate with cache system
                cached_decision_engine = await self.cache_system.integrate_with_decision_engine(wrapped_decision_engine)
                
                integrated_components["decision_engine"] = cached_decision_engine
                
                self.integration_status["decision_engine"] = IntegrationStatus(
                    component="decision_engine",
                    integrated=True,
                    integration_time=datetime.now()
                )
                
                self.logger.info("DecisionEngine integration completed")
            
            # Integrate orchestration runtime
            if orchestration_runtime:
                self.logger.info("Integrating orchestration runtime with optimization...")
                
                # Wrap with reasoning preservation layer
                wrapped_flow_manager = self.reasoning_preservation_layer.wrap_flow_manager(
                    orchestration_runtime
                )
                
                # Integrate with cache system
                cached_flow_manager = await self.cache_system.integrate_with_flow_manager(wrapped_flow_manager)
                
                integrated_components["orchestration_runtime"] = cached_flow_manager
                
                self.integration_status["orchestration_runtime"] = IntegrationStatus(
                    component="orchestration_runtime",
                    integrated=True,
                    integration_time=datetime.now()
                )
                
                self.logger.info("Orchestration runtime integration completed")
            
            # Integrate Scaffolding Service
            if scaffolding_service:
                self.logger.info("Integrating Intelligent Scaffolding Service with optimization...")
                
                # Wrap with reasoning preservation layer
                wrapped_scaffolding = self.reasoning_preservation_layer.wrap_scaffolding_service(scaffolding_service)
                
                # Integrate with cache system
                cached_scaffolding = await self.cache_system.integrate_with_small_language_model_service(wrapped_scaffolding)
                
                integrated_components["scaffolding_service"] = cached_scaffolding
                
                self.integration_status["scaffolding_service"] = IntegrationStatus(
                    component="scaffolding_service",
                    integrated=True,
                    integration_time=datetime.now()
                )
                
                self.logger.info("Intelligent Scaffolding Service integration completed")
            
            # Backward compatibility: If no scaffolding service provided, create one
            if not scaffolding_service:
                self.logger.info("Creating default Intelligent Scaffolding Service...")
                from ai_karen_engine.services.optimization.intelligent_scaffolding_service import (
                    get_intelligent_scaffolding_service,
                )
                
                default_scaffolding = get_intelligent_scaffolding_service()
                wrapped_scaffolding = self.reasoning_preservation_layer.wrap_scaffolding_service(default_scaffolding)
                cached_scaffolding = await self.cache_system.integrate_with_small_language_model_service(wrapped_scaffolding)
                
                integrated_components["scaffolding_service"] = cached_scaffolding
                
                self.integration_status["scaffolding_service"] = IntegrationStatus(
                    component="scaffolding_service",
                    integrated=True,
                    integration_time=datetime.now()
                )
                
                self.logger.info("Default Intelligent Scaffolding Service created and integrated")
            
            # Store integrated components
            with self._lock:
                self.integrated_components.update(integrated_components)
            
            self.logger.info(f"Successfully integrated {len(integrated_components)} reasoning components")
            return integrated_components
            
        except Exception as e:
            self.logger.error(f"Failed to integrate reasoning components: {e}")
            
            # Update error status
            for component in ["decision_engine", "flow_manager", "scaffolding_service"]:
                if component not in self.integration_status:
                    self.integration_status[component] = IntegrationStatus(
                        component=component,
                        integrated=False,
                        error_message=str(e)
                    )
            
            raise
    
    def get_integrated_component(self, component_name: str) -> Optional[Any]:
        """Get an integrated component by name."""
        with self._lock:
            return self.integrated_components.get(component_name)
    
    def get_integration_status(self) -> Dict[str, Any]:
        """Get comprehensive integration status."""
        with self._lock:
            return {
                "initialized": self._initialized,
                "initialization_error": self._initialization_error,
                "component_status": {
                    name: {
                        "integrated": status.integrated,
                        "error_message": status.error_message,
                        "integration_time": status.integration_time.isoformat() if status.integration_time else None
                    }
                    for name, status in self.integration_status.items()
                },
                "integrated_components": list(self.integrated_components.keys()),
                "configuration_summary": self.config_manager.get_configuration_summary(),
                "model_management_status": self.model_manager.get_integration_status(),
                "cache_system_metrics": self.cache_system.get_integration_metrics(),
                "performance_monitoring_status": self.performance_monitor.get_integration_status(),
                "reasoning_preservation_stats": self.reasoning_preservation_layer.get_reasoning_statistics()
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check of integrated system."""
        try:
            health_status = {
                "overall_health": "healthy",
                "timestamp": datetime.now().isoformat(),
                "components": {}
            }
            
            # Check initialization
            if not self._initialized:
                health_status["overall_health"] = "unhealthy"
                health_status["initialization_error"] = self._initialization_error
            
            # Check each component
            for component_name, status in self.integration_status.items():
                component_health = {
                    "status": "healthy" if status.integrated else "unhealthy",
                    "error": status.error_message
                }
                
                if not status.integrated:
                    health_status["overall_health"] = "degraded"
                
                health_status["components"][component_name] = component_health
            
            # Check model management health
            try:
                model_status = self.model_manager.get_integration_status()
                health_status["components"]["model_management"]["details"] = {
                    "discovery_rate": model_status["integration_health"]["discovery_rate"],
                    "verification_rate": model_status["integration_health"]["verification_rate"],
                    "routing_rate": model_status["integration_health"]["routing_rate"]
                }
            except Exception as e:
                health_status["components"]["model_management"]["error"] = str(e)
            
            # Check cache system health
            try:
                cache_metrics = self.cache_system.get_integration_metrics()
                health_status["components"]["cache_system"]["details"] = {
                    "hit_rate": cache_metrics["hit_rate"],
                    "total_requests": cache_metrics["total_requests"]
                }
            except Exception as e:
                health_status["components"]["cache_system"]["error"] = str(e)
            
            # Check performance monitoring health
            try:
                perf_status = self.performance_monitor.get_integration_status()
                health_status["components"]["performance_monitoring"]["details"] = {
                    "monitoring_active": perf_status["monitoring_active"],
                    "metrics_collected": perf_status["total_metrics_collected"],
                    "active_alerts": perf_status["active_alerts_count"]
                }
            except Exception as e:
                health_status["components"]["performance_monitoring"]["error"] = str(e)
            
            return health_status
            
        except Exception as e:
            return {
                "overall_health": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def add_integration_callback(self, callback: Callable):
        """Add callback for integration events."""
        self.integration_callbacks.append(callback)
        self.logger.debug("Added integration callback")
    
    def remove_integration_callback(self, callback: Callable):
        """Remove integration callback."""
        try:
            self.integration_callbacks.remove(callback)
            self.logger.debug("Removed integration callback")
        except ValueError:
            pass
    
    async def shutdown(self):
        """Shutdown the integration orchestrator and cleanup resources."""
        try:
            self.logger.info("Shutting down optimization integration orchestrator...")
            
            # Stop performance monitoring
            await self.performance_monitor.stop_monitoring()
            
            # Clear integrated components
            with self._lock:
                self.integrated_components.clear()
                self.integration_status.clear()
            
            # Clear callbacks
            self.integration_callbacks.clear()
            
            self._initialized = False
            
            self.logger.info("Optimization integration orchestrator shutdown completed")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")

# Global instance
_integration_orchestrator: Optional[OptimizationIntegrationOrchestrator] = None
_orchestrator_lock = threading.RLock()

def get_optimization_integration_orchestrator() -> OptimizationIntegrationOrchestrator:
    """Get the global optimization integration orchestrator instance."""
    global _integration_orchestrator
    if _integration_orchestrator is None:
        with _orchestrator_lock:
            if _integration_orchestrator is None:
                _integration_orchestrator = OptimizationIntegrationOrchestrator()
    return _integration_orchestrator

async def initialize_optimization_integration() -> OptimizationIntegrationOrchestrator:
    """Initialize the complete optimization integration system."""
    orchestrator = get_optimization_integration_orchestrator()
    await orchestrator.initialize_integration()
    return orchestrator

# Convenience functions for easy integration
async def integrate_reasoning_system(
    decision_engine: Optional[DecisionEngine] = None,
    orchestration_runtime: Optional[OrchestrationRuntime] = None,
    scaffolding_service: Optional[IntelligentScaffoldingService] = None
) -> Dict[str, Any]:
    """
    Convenience function to integrate reasoning system with optimization.
    
    This is the main entry point for integrating existing reasoning components
    with the optimization system while preserving all their functionality.
    """
    orchestrator = get_optimization_integration_orchestrator()
    
    # Initialize if not already done
    if not orchestrator._initialized:
        await orchestrator.initialize_integration()
    
    # Integrate components
    return await orchestrator.integrate_reasoning_components(
        decision_engine=decision_engine,
        orchestration_runtime=orchestration_runtime,
        scaffolding_service=scaffolding_service
    )

def get_integrated_reasoning_component(component_name: str) -> Optional[Any]:
    """Get an integrated reasoning component by name."""
    orchestrator = get_optimization_integration_orchestrator()
    return orchestrator.get_integrated_component(component_name)
