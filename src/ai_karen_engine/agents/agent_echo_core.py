"""
Agent Echo Core Service

.. deprecated::
    The legacy echo core is deprecated. Echo/messaging functionality is now
    handled by the canonical runtime and Medusa event system.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.services.base import BaseService, ServiceConfig, ServiceStatus

warnings.warn(
    "ai_karen_engine.agents.agent_echo_core is deprecated.",
    DeprecationWarning,
    stacklevel=2,
)


class AgentEchoCore(BaseService):
    """
    Agent Echo Core service for providing core echo functionality to agents.
    
    This service provides capabilities for agents to echo and process messages,
    supporting various formats and transformations.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_echo_core"))
        self._initialized = False
        self._echo_history: List[Dict[str, Any]] = []
        self._echo_formats: Dict[str, str] = {
            "text": "text/plain",
            "json": "application/json",
            "xml": "application/xml",
            "html": "text/html"
        }
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> bool:
        """Initialize the Agent Echo Core service."""
        try:
            self.logger.info("Initializing Agent Echo Core service")
            
            # Initialize echo formats
            await self._initialize_echo_formats()
            
            self._initialized = True
            self._status = ServiceStatus.RUNNING
            self.logger.info("Agent Echo Core service initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Agent Echo Core service: {e}")
            self._status = ServiceStatus.ERROR
            return False
    
    async def shutdown(self) -> bool:
        """Shutdown the Agent Echo Core service."""
        try:
            self.logger.info("Shutting down Agent Echo Core service")
            
            # Clear echo history
            async with self._lock:
                self._echo_history.clear()
            
            self._initialized = False
            self._status = ServiceStatus.STOPPED
            self.logger.info("Agent Echo Core service shutdown successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to shutdown Agent Echo Core service: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check the health of the Agent Echo Core service."""
        return self._initialized and self._status == ServiceStatus.RUNNING
    
    async def echo_message(
        self,
        message: str,
        format_type: str = "text",
        transform: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Echo a message with optional formatting and transformation.
        
        Args:
            message: The message to echo
            format_type: The format type (text, json, xml, html)
            transform: Optional transformation to apply
            
        Returns:
            Dictionary containing the echoed message and metadata
        """
        if not self._initialized:
            raise RuntimeError("Agent Echo Core service is not initialized")
        
        if format_type not in self._echo_formats:
            raise ValueError(f"Unsupported format type: {format_type}")
        
        # Apply transformation if specified
        processed_message = message
        if transform:
            processed_message = await self._apply_transformation(message, transform)
        
        # Format the message
        formatted_message = await self._format_message(processed_message, format_type)
        
        # Create response
        response = {
            "original_message": message,
            "processed_message": processed_message,
            "formatted_message": formatted_message,
            "format_type": format_type,
            "content_type": self._echo_formats[format_type],
            "transform_applied": transform is not None,
            "transform_type": transform
        }
        
        # Add to echo history
        async with self._lock:
            self._echo_history.append({
                "timestamp": asyncio.get_event_loop().time(),
                "message": message,
                "format_type": format_type,
                "transform": transform
            })
        
        return response
    
    async def batch_echo(
        self,
        messages: List[str],
        format_type: str = "text",
        transform: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Echo multiple messages with optional formatting and transformation.
        
        Args:
            messages: List of messages to echo
            format_type: The format type (text, json, xml, html)
            transform: Optional transformation to apply
            
        Returns:
            List of dictionaries containing the echoed messages and metadata
        """
        if not self._initialized:
            raise RuntimeError("Agent Echo Core service is not initialized")
        
        results = []
        for message in messages:
            result = await self.echo_message(message, format_type, transform)
            results.append(result)
        
        return results
    
    async def get_echo_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get the echo history.
        
        Args:
            limit: Optional limit on the number of history items to return
            
        Returns:
            List of echo history items
        """
        if not self._initialized:
            raise RuntimeError("Agent Echo Core service is not initialized")
        
        async with self._lock:
            if limit is None:
                return self._echo_history.copy()
            else:
                return self._echo_history[-limit:]
    
    async def get_supported_formats(self) -> Dict[str, str]:
        """
        Get the supported echo formats.
        
        Returns:
            Dictionary mapping format types to content types
        """
        if not self._initialized:
            raise RuntimeError("Agent Echo Core service is not initialized")
        
        return self._echo_formats.copy()
    
    async def get_supported_transformations(self) -> List[str]:
        """
        Get the supported transformations.
        
        Returns:
            List of supported transformation names
        """
        if not self._initialized:
            raise RuntimeError("Agent Echo Core service is not initialized")
        
        return ["uppercase", "lowercase", "reverse", "capitalize", "title"]
    
    async def _initialize_echo_formats(self) -> None:
        """Initialize echo formats."""
        # Additional formats can be added here
        pass
    
    async def _apply_transformation(self, message: str, transform: str) -> str:
        """
        Apply a transformation to a message.
        
        Args:
            message: The message to transform
            transform: The transformation type
            
        Returns:
            The transformed message
        """
        transformations = {
            "uppercase": lambda x: x.upper(),
            "lowercase": lambda x: x.lower(),
            "reverse": lambda x: x[::-1],
            "capitalize": lambda x: x.capitalize(),
            "title": lambda x: x.title()
        }
        
        if transform not in transformations:
            raise ValueError(f"Unsupported transformation: {transform}")
        
        return transformations[transform](message)
    
    async def _format_message(self, message: str, format_type: str) -> str:
        """
        Format a message according to the specified format type.
        
        Args:
            message: The message to format
            format_type: The format type
            
        Returns:
            The formatted message
        """
        if format_type == "text":
            return message
        elif format_type == "json":
            import json
            return json.dumps({"message": message})
        elif format_type == "xml":
            return f"<message>{message}</message>"
        elif format_type == "html":
            return f"<div class='echo-message'>{message}</div>"
        else:
            raise ValueError(f"Unsupported format type: {format_type}")