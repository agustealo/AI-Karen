"""
Deployment Configuration Integration

This module integrates the deployment configuration manager with the existing
service lifecycle management and performance optimization systems.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime

from .deployment_config_manager import (
    DeploymentConfigManager, DeploymentMode, ServiceConfig,
    ConfigChange, ConfigChangeType
)
from .deployment_validator import DeploymentValidator, ValidationResult
from ..core.service_lifecycle_manager import ServiceLifecycleManager
from ..core.lazy_loading_controller import LazyLoadingController
from ..core.resource_monitor import ResourceMonitor
from ..core.observability.performance_metrics import PerformanceMetrics

logger = logging.getLogger(__name__)


@dataclass
class ServiceState:
    """Current state of a service"""
    name: str
    is_running: bool
    is_enabled: bool
    last_started: Optional[datetime] = None
    last_stopped: Optional[datetime] = None
    resource_usage: Optional[Dict[str, Any]] = None
    health_status: str = "unknown"


class DeploymentOrchestrator:
    """
    Orchestrates deployment configuration with service lifecycle management.
    
    This class bridges the deployment configuration system with the actual
    service management components, ensuring that configuration changes are
    properly applied to running services.
    """
    
    def __init__(
        self,
        config_manager: DeploymentConfigManager,
        service_lifecycle_manager: Optional[ServiceLifecycleManager] = None,
        lazy_loading_controller: Optional[LazyLoadingController] = None,
        resource_monitor: Optional[ResourceMonitor] = None,
        performance_metrics: Optional[PerformanceMetrics] = None,
        validator: Optional[DeploymentValidator] = None
    ):
        """
        Initialize deployment orchestrator.
        
        Args:
            config_manager: Deployment configuration manager
            service_lifecycle_manager: Service lifecycle manager
            lazy_loading_controller: Lazy loading controller
            resource_monitor: Resource monitor
            performance_metrics: Performance metrics collector
            validator: Configuration validator
        """
        self.config_manager = config_manager
        self.service_lifecycle_manager = service_lifecycle_manager
        self.lazy_loading_controller = lazy_loading_controller
        self.resource_monitor = resource_monitor
        self.performance_metrics = performance_metrics
        self.validator = validator or DeploymentValidator()
        
        # Service state tracking
        self._service_states: Dict[str, ServiceState] = {}
        self._state_lock = asyncio.Lock()
        
        # Event handlers
        self._deployment_listeners: List[Callable[[str, ServiceState], None]] = []
        
        # Register for configuration changes
        self.config_manager.add_change_listener(self._handle_config_change)
        self.config_manager.add_service_listener(self._handle_service_change)
        
        logger.info("Deployment orchestrator initialized")
    
    async def initialize(self) -> None:
        """Initialize the deployment orchestrator"""
        try:
            # Initialize service states
            await self._initialize_service_states()
            
            # Apply current deployment configuration
            await self._apply_deployment_configuration()
            
            logger.info("Deployment orchestrator initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize deployment orchestrator: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown the deployment orchestrator"""
        try:
            # Gracefully stop all services
            await self._shutdown_all_services()
            
            logger.info("Deployment orchestrator shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during deployment orchestrator shutdown: {e}")
    
    async def apply_deployment_mode(self, mode: DeploymentMode) -> bool:
        """
        Apply a deployment mode configuration.
        
        Args:
            mode: Deployment mode to apply
            
        Returns:
            True if deployment was successful
        """
        try:
            logger.info(f"Applying deployment mode: {mode}")
            
            # Validate configuration before applying
            if self.validator:
                services = self.config_manager.get_all_services()
                profiles = self.config_manager.get_deployment_profiles()
                
                validation_result = await self.validator.validate_deployment_configuration(
                    services, profiles, mode
                )
                
                if not validation_result.is_valid:
                    logger.error(f"Deployment mode validation failed: {validation_result.errors_count} errors")
                    return False
            
            # Set deployment mode
            await self.config_manager.set_deployment_mode(mode)
            
            # Apply the configuration
            await self._apply_deployment_configuration()
            
            logger.info(f"Deployment mode {mode} applied successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply deployment mode {mode}: {e}")
            return False
    
    async def get_service_status(self, service_name: str) -> Optional[ServiceState]:
        """Get current status of a service"""
        async with self._state_lock:
            return self._service_states.get(service_name)
    
    async def get_all_service_states(self) -> Dict[str, ServiceState]:
        """Get current states of all services"""
        async with self._state_lock:
            return self._service_states.copy()
    
    async def get_deployment_health(self) -> Dict[str, Any]:
        """Get overall deployment health status"""
        try:
            service_states = await self.get_all_service_states()
            
            total_services = len(service_states)
            running_services = sum(1 for state in service_states.values() if state.is_running)
            enabled_services = sum(1 for state in service_states.values() if state.is_enabled)
            
            # Get resource allocation
            allocation = await self.config_manager.get_resource_allocation()
            
            # Calculate health score
            health_score = (running_services / max(enabled_services, 1)) * 100
            
            health_status = "healthy"
            if health_score < 50:
                health_status = "critical"
            elif health_score < 80:
                health_status = "degraded"
            
            return {
                'overall_status': health_status,
                'health_score': health_score,
                'services': {
                    'total': total_services,
                    'running': running_services,
                    'enabled': enabled_services,
                    'stopped': enabled_services - running_services
                },
                'resource_allocation': allocation,
                'deployment_mode': self.config_manager.get_current_mode().value,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to get deployment health: {e}")
            return {
                'overall_status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    async def optimize_deployment(self) -> Dict[str, Any]:
        """
        Optimize current deployment based on resource usage and performance metrics.
        
        Returns:
            Dictionary with optimization results
        """
        try:
            logger.info("Starting deployment optimization")
            
            optimization_results = {
                'actions_taken': [],
                'recommendations': [],
                'resource_savings': {},
                'performance_improvements': {}
            }
            
            # Get current resource usage
            if self.resource_monitor:
                resource_metrics = await self.resource_monitor.get_current_metrics()
                
                # Check for resource pressure
                if resource_metrics.get('memory_usage_percent', 0) > 80:
                    # Suspend idle background services
                    suspended = await self._suspend_idle_background_services()
                    if suspended:
                        optimization_results['actions_taken'].append(
                            f"Suspended {len(suspended)} idle background services"
                        )
            
            # Get optimization suggestions from validator
            if self.validator:
                services = self.config_manager.get_all_services()
                profiles = self.config_manager.get_deployment_profiles()
                mode = self.config_manager.get_current_mode()
                
                suggestions = await self.validator.get_optimization_suggestions(
                    services, profiles, mode
                )
                
                optimization_results['recommendations'] = [
                    {
                        'message': suggestion.message,
                        'suggested_fix': suggestion.suggested_fix,
                        'category': suggestion.category
                    }
                    for suggestion in suggestions
                ]
            
            # Check for service consolidation opportunities
            consolidation_opportunities = await self._identify_consolidation_opportunities()
            if consolidation_opportunities:
                optimization_results['recommendations'].extend([
                    {
                        'message': f"Consider consolidating services: {', '.join(group)}",
                        'suggested_fix': "Merge related services to reduce overhead",
                        'category': 'consolidation'
                    }
                    for group in consolidation_opportunities
                ])
            
            logger.info("Deployment optimization complete")
            return optimization_results
            
        except Exception as e:
            logger.error(f"Deployment optimization failed: {e}")
            return {
                'error': str(e),
                'actions_taken': [],
                'recommendations': []
            }
    
    def add_deployment_listener(self, listener: Callable[[str, ServiceState], None]) -> None:
        """Add deployment event listener"""
        self._deployment_listeners.append(listener)
    
    def remove_deployment_listener(self, listener: Callable[[str, ServiceState], None]) -> None:
        """Remove deployment event listener"""
        if listener in self._deployment_listeners:
            self._deployment_listeners.remove(listener)
    
    # Private methods
    
    async def _initialize_service_states(self) -> None:
        """Initialize service state tracking"""
        async with self._state_lock:
            services = self.config_manager.get_all_services()
            
            for service_name, service_config in services.items():
                self._service_states[service_name] = ServiceState(
                    name=service_name,
                    is_running=False,
                    is_enabled=service_config.enabled
                )
    
    async def _apply_deployment_configuration(self) -> None:
        """Apply current deployment configuration to services"""
        try:
            # Get services for current mode
            target_services = await self.config_manager.get_services_for_current_mode()
            
            async with self._state_lock:
                # Stop services that should not be running
                for service_name, state in self._service_states.items():
                    if state.is_running and service_name not in target_services:
                        await self._stop_service_internal(service_name)
                
                # Start services that should be running
                for service_name in target_services:
                    state = self._service_states.get(service_name)
                    if state and not state.is_running:
                        await self._start_service_internal(service_name)
            
            logger.info(f"Applied deployment configuration: {len(target_services)} services active")
            
        except Exception as e:
            logger.error(f"Failed to apply deployment configuration: {e}")
            raise
    
    async def _start_service_internal(self, service_name: str) -> bool:
        """Start a service internally"""
        try:
            service_config = self.config_manager.get_service_config(service_name)
            if not service_config:
                logger.error(f"Service configuration not found: {service_name}")
                return False
            
            # Use service lifecycle manager if available
            if self.service_lifecycle_manager:
                success = await self.service_lifecycle_manager.start_service(service_name)
                if not success:
                    logger.error(f"Failed to start service via lifecycle manager: {service_name}")
                    return False
            
            # Update service state
            state = self._service_states.get(service_name)
            if state:
                state.is_running = True
                state.last_started = datetime.now()
                state.health_status = "starting"
            
            # Register with lazy loading controller if available
            if self.lazy_loading_controller and service_config.classification.value != 'essential':
                # Register for lazy loading
                pass  # Implementation would depend on lazy loading controller interface
            
            logger.info(f"Service started: {service_name}")
            await self._notify_deployment_listeners("started", state)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start service {service_name}: {e}")
            return False
    
    async def _stop_service_internal(self, service_name: str) -> bool:
        """Stop a service internally"""
        try:
            # Use service lifecycle manager if available
            if self.service_lifecycle_manager:
                success = await self.service_lifecycle_manager.stop_service(service_name)
                if not success:
                    logger.error(f"Failed to stop service via lifecycle manager: {service_name}")
                    return False
            
            # Update service state
            state = self._service_states.get(service_name)
            if state:
                state.is_running = False
                state.last_stopped = datetime.now()
                state.health_status = "stopped"
            
            logger.info(f"Service stopped: {service_name}")
            await self._notify_deployment_listeners("stopped", state)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop service {service_name}: {e}")
            return False
    
    async def _suspend_idle_background_services(self) -> List[str]:
        """Suspend idle background services to free resources"""
        suspended_services = []
        
        try:
            async with self._state_lock:
                for service_name, state in self._service_states.items():
                    if not state.is_running:
                        continue
                    
                    service_config = self.config_manager.get_service_config(service_name)
                    if (service_config and 
                        service_config.classification.value == 'background' and
                        service_config.idle_timeout):
                        
                        # Check if service has been idle
                        # In a real implementation, you would check actual idle time
                        # For now, we'll suspend background services under resource pressure
                        if await self._stop_service_internal(service_name):
                            suspended_services.append(service_name)
            
            if suspended_services:
                logger.info(f"Suspended idle background services: {suspended_services}")
            
            return suspended_services
            
        except Exception as e:
            logger.error(f"Failed to suspend idle services: {e}")
            return []
    
    async def _identify_consolidation_opportunities(self) -> List[List[str]]:
        """Identify services that could be consolidated"""
        consolidation_groups = []
        
        try:
            services = self.config_manager.get_all_services()
            
            # Group services by consolidation group
            groups = {}
            for service_name, service_config in services.items():
                if service_config.consolidation_group:
                    group = service_config.consolidation_group
                    if group not in groups:
                        groups[group] = []
                    groups[group].append(service_name)
            
            # Return groups with more than one service
            consolidation_groups = [group for group in groups.values() if len(group) > 1]
            
        except Exception as e:
            logger.error(f"Failed to identify consolidation opportunities: {e}")
        
        return consolidation_groups
    
    async def _shutdown_all_services(self) -> None:
        """Gracefully shutdown all running services"""
        try:
            async with self._state_lock:
                running_services = [
                    name for name, state in self._service_states.items() 
                    if state.is_running
                ]
            
            # Stop services in reverse priority order
            services = self.config_manager.get_all_services()
            sorted_services = sorted(
                running_services,
                key=lambda name: services.get(name, ServiceConfig(name="", classification="optional")).startup_priority,
                reverse=True
            )
            
            for service_name in sorted_services:
                await self._stop_service_internal(service_name)
            
            logger.info("All services shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during service shutdown: {e}")
    
    async def _handle_config_change(self, change: ConfigChange) -> None:
        """Handle configuration change events"""
        try:
            logger.info(f"Handling configuration change: {change.change_type}")
            
            if change.change_type == ConfigChangeType.DEPLOYMENT_MODE_CHANGED:
                await self._apply_deployment_configuration()
            elif change.change_type in [ConfigChangeType.SERVICE_ADDED, ConfigChangeType.SERVICE_REMOVED]:
                await self._apply_deployment_configuration()
            elif change.change_type == ConfigChangeType.SERVICE_MODIFIED:
                # Handle service configuration updates
                for service_name in change.affected_services:
                    # Restart service if it's running to apply new configuration
                    state = await self.get_service_status(service_name)
                    if state and state.is_running:
                        await self._stop_service_internal(service_name)
                        await self._start_service_internal(service_name)
            
        except Exception as e:
            logger.error(f"Failed to handle configuration change: {e}")
    
    async def _handle_service_change(self, service_name: str, action: str) -> None:
        """Handle service state change events"""
        try:
            logger.debug(f"Handling service change: {service_name} -> {action}")
            
            if action == "start":
                await self._start_service_internal(service_name)
            elif action == "stop":
                await self._stop_service_internal(service_name)
            elif action == "update":
                # Service configuration was updated
                state = await self.get_service_status(service_name)
                if state and state.is_running:
                    # Restart to apply new configuration
                    await self._stop_service_internal(service_name)
                    await self._start_service_internal(service_name)
            
        except Exception as e:
            logger.error(f"Failed to handle service change: {e}")
    
    async def _notify_deployment_listeners(self, action: str, state: ServiceState) -> None:
        """Notify deployment event listeners"""
        for listener in self._deployment_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(action, state)
                else:
                    listener(action, state)
            except Exception as e:
                logger.error(f"Error notifying deployment listener: {e}")


class DeploymentManager:
    """
    High-level deployment manager that coordinates all deployment components.
    
    This class provides a unified interface for deployment configuration management,
    service orchestration, and performance optimization.
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        enable_hot_reload: bool = True,
        enable_validation: bool = True,
        enable_optimization: bool = True
    ):
        """
        Initialize deployment manager.
        
        Args:
            config_path: Path to configuration file
            enable_hot_reload: Enable configuration hot reloading
            enable_validation: Enable configuration validation
            enable_optimization: Enable automatic optimization
        """
        # Initialize core components
        self.config_manager = DeploymentConfigManager(
            config_path=config_path,
            enable_hot_reload=enable_hot_reload,
            enable_validation=enable_validation
        )
        
        self.validator = DeploymentValidator()
        
        # Initialize performance components (would be injected in real implementation)
        self.service_lifecycle_manager = None  # ServiceLifecycleManager()
        self.lazy_loading_controller = None    # LazyLoadingController()
        self.resource_monitor = None           # ResourceMonitor()
        self.performance_metrics = None        # PerformanceMetrics()
        
        # Initialize orchestrator
        self.orchestrator = DeploymentOrchestrator(
            config_manager=self.config_manager,
            service_lifecycle_manager=self.service_lifecycle_manager,
            lazy_loading_controller=self.lazy_loading_controller,
            resource_monitor=self.resource_monitor,
            performance_metrics=self.performance_metrics,
            validator=self.validator
        )
        
        self.enable_optimization = enable_optimization
        self._optimization_task: Optional[asyncio.Task] = None
        
        logger.info("Deployment manager initialized")
    
    async def start(self) -> None:
        """Start the deployment manager"""
        try:
            await self.config_manager.initialize()
            await self.orchestrator.initialize()
            
            if self.enable_optimization:
                self._optimization_task = asyncio.create_task(self._optimization_loop())
            
            logger.info("Deployment manager started")
            
        except Exception as e:
            logger.error(f"Failed to start deployment manager: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the deployment manager"""
        try:
            if self._optimization_task:
                self._optimization_task.cancel()
                try:
                    await self._optimization_task
                except asyncio.CancelledError:
                    pass
            
            await self.orchestrator.shutdown()
            await self.config_manager.shutdown()
            
            logger.info("Deployment manager stopped")
            
        except Exception as e:
            logger.error(f"Error stopping deployment manager: {e}")
    
    async def set_deployment_mode(self, mode: DeploymentMode) -> bool:
        """Set deployment mode"""
        return await self.orchestrator.apply_deployment_mode(mode)
    
    async def get_deployment_status(self) -> Dict[str, Any]:
        """Get comprehensive deployment status"""
        try:
            health = await self.orchestrator.get_deployment_health()
            service_states = await self.orchestrator.get_all_service_states()
            
            return {
                'health': health,
                'services': {
                    name: {
                        'running': state.is_running,
                        'enabled': state.is_enabled,
                        'health_status': state.health_status,
                        'last_started': state.last_started.isoformat() if state.last_started else None,
                        'last_stopped': state.last_stopped.isoformat() if state.last_stopped else None
                    }
                    for name, state in service_states.items()
                },
                'configuration': {
                    'mode': self.config_manager.get_current_mode().value,
                    'profiles': list(self.config_manager.get_deployment_profiles().keys()),
                    'total_services': len(self.config_manager.get_all_services())
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get deployment status: {e}")
            return {'error': str(e)}
    
    async def optimize_deployment(self) -> Dict[str, Any]:
        """Manually trigger deployment optimization"""
        return await self.orchestrator.optimize_deployment()
    
    # Private methods
    
    async def _optimization_loop(self) -> None:
        """Automatic optimization loop"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                
                logger.debug("Running automatic deployment optimization")
                await self.orchestrator.optimize_deployment()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying