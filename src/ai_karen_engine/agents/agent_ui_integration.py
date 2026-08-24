"""
Agent UI Integration Service

.. deprecated::
    The legacy UI integration service is deprecated. UI integration should use
    ``ai_karen_engine.copilotkit`` or direct API routes.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.services.base import BaseService, ServiceConfig, ServiceStatus

warnings.warn(
    "ai_karen_engine.agents.agent_ui_integration is deprecated. "
    "Use ai_karen_engine.copilotkit or direct API routes instead.",
    DeprecationWarning,
    stacklevel=2,
)


class AgentUIIntegration(BaseService):
    """
    Agent UI Integration service for providing UI integration capabilities to agents.
    
    This service provides capabilities for agents to interact with user interfaces,
    handle UI events, and manage UI state.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_ui_integration"))
        self._initialized = False
        self._ui_components: Dict[str, Dict[str, Any]] = {}
        self._ui_events: List[Dict[str, Any]] = []
        self._ui_state: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> bool:
        """Initialize the Agent UI Integration service."""
        try:
            self.logger.info("Initializing Agent UI Integration service")
            
            # Initialize UI components
            await self._initialize_ui_components()
            
            self._initialized = True
            self._status = ServiceStatus.RUNNING
            self.logger.info("Agent UI Integration service initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Agent UI Integration service: {e}")
            self._status = ServiceStatus.ERROR
            return False
    
    async def shutdown(self) -> bool:
        """Shutdown the Agent UI Integration service."""
        try:
            self.logger.info("Shutting down Agent UI Integration service")
            
            # Clear UI components and events
            async with self._lock:
                self._ui_components.clear()
                self._ui_events.clear()
                self._ui_state.clear()
            
            self._initialized = False
            self._status = ServiceStatus.STOPPED
            self.logger.info("Agent UI Integration service shutdown successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to shutdown Agent UI Integration service: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check the health of the Agent UI Integration service."""
        return self._initialized and self._status == ServiceStatus.RUNNING
    
    async def register_ui_component(
        self,
        component_id: str,
        component_type: str,
        properties: Dict[str, Any]
    ) -> bool:
        """
        Register a UI component.
        
        Args:
            component_id: The ID of the component
            component_type: The type of the component
            properties: The properties of the component
            
        Returns:
            True if the component was registered successfully, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            self._ui_components[component_id] = {
                "type": component_type,
                "properties": properties,
                "created_at": asyncio.get_event_loop().time()
            }
        
        return True
    
    async def unregister_ui_component(self, component_id: str) -> bool:
        """
        Unregister a UI component.
        
        Args:
            component_id: The ID of the component
            
        Returns:
            True if the component was unregistered successfully, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            if component_id in self._ui_components:
                del self._ui_components[component_id]
                return True
            else:
                return False
    
    async def get_ui_component(self, component_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a UI component.
        
        Args:
            component_id: The ID of the component
            
        Returns:
            The component information or None if not found
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            return self._ui_components.get(component_id)
    
    async def get_all_ui_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all UI components.
        
        Returns:
            Dictionary mapping component IDs to component information
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            return self._ui_components.copy()
    
    async def emit_ui_event(
        self,
        event_type: str,
        component_id: str,
        event_data: Dict[str, Any]
    ) -> bool:
        """
        Emit a UI event.
        
        Args:
            event_type: The type of the event
            component_id: The ID of the component that emitted the event
            event_data: The data associated with the event
            
        Returns:
            True if the event was emitted successfully, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            self._ui_events.append({
                "type": event_type,
                "component_id": component_id,
                "data": event_data,
                "timestamp": asyncio.get_event_loop().time()
            })
        
        return True
    
    async def get_ui_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get UI events.
        
        Args:
            limit: Optional limit on the number of events to return
            
        Returns:
            List of UI events
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            if limit is None:
                return self._ui_events.copy()
            else:
                return self._ui_events[-limit:]
    
    async def update_ui_state(self, state_updates: Dict[str, Any]) -> bool:
        """
        Update the UI state.
        
        Args:
            state_updates: The state updates to apply
            
        Returns:
            True if the state was updated successfully, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            self._ui_state.update(state_updates)
        
        return True
    
    async def get_ui_state(self) -> Dict[str, Any]:
        """
        Get the current UI state.
        
        Returns:
            The current UI state
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            return self._ui_state.copy()
    
    async def get_ui_state_value(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the UI state.
        
        Args:
            key: The key to get
            default: The default value to return if the key is not found
            
        Returns:
            The value associated with the key or the default value
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            return self._ui_state.get(key, default)
    
    async def clear_ui_events(self) -> bool:
        """
        Clear all UI events.
        
        Returns:
            True if the events were cleared successfully, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Agent UI Integration service is not initialized")
        
        async with self._lock:
            self._ui_events.clear()
        
        return True
    
    async def _initialize_ui_components(self) -> None:
        """Initialize UI components."""
        # Default UI components can be added here
        pass