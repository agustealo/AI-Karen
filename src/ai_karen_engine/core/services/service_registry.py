"""
Service registry for AI Karen services.
Provides a centralized way to access services.
"""

from typing import Any, Optional
from ai_karen_engine.core.services.container import get_container

class ServiceRegistry:
    """Registry for accessing services."""
    
    def __init__(self):
        self._container = get_container()
    
    def get_service(self, service_name: str) -> Any:
        """Get a service by name."""
        return self._container.get_service(service_name)
    
    def has_service(self, service_name: str) -> bool:
        """Check if a service exists."""
        return self._container.has_service(service_name)

# Global registry instance
_registry: Optional[ServiceRegistry] = None

def get_service_registry() -> ServiceRegistry:
    """Get the global service registry instance."""
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry