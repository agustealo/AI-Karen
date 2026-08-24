"""
Communication System for Agent Architecture.

.. deprecated::
    The legacy communication system is deprecated. Inter-component communication
    is handled by the canonical runtime and Medusa event system.
"""

import os
import logging
import asyncio
import json
import warnings
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable
from datetime import datetime
from enum import Enum

warnings.warn(
    "ai_karen_engine.agents.communication is deprecated.",
    DeprecationWarning,
    stacklevel=2,
)
import traceback

# Third-party modules
try:
    import websockets as websockets_module
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    # Create placeholder class for type hints
    class websockets:
        class WebSocketServerProtocol:
            pass
        
        @staticmethod
        async def connect(uri):
            raise NotImplementedError("WebSockets library is not installed")

try:
    import aiohttp as aiohttp_module
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    # Create placeholder class for type hints
    class aiohttp:
        class ClientSession:
            def __init__(self, **kwargs):
                pass
                
            async def close(self):
                pass
                
            async def post(self, url, **kwargs):
                class MockResponse:
                    status = 500
                return MockResponse()
                
        class ClientTimeout:
            def __init__(self, total=None):
                pass

# Local application imports
from .internal.agent_schemas import (
    AgentDefinition, AgentTask, AgentResponse, AgentTool, AgentMemory,
    AgentStatus, TaskStatus, MessageStatus, AgentMessage
)
from .internal.agent_validation import AgentValidation
from .adapters.langchain_adapter import LangChainAdapter
from .adapters.deepagents_adapter import DeepAgentsAdapter
from .bridges.karen_langchain_bridge import KarenLangChainBridge
from .bridges.karen_deepagents_bridge import KarenDeepAgentsBridge
from .agent_memory import EnhancedAgentMemory
from .agent_tool_broker import AgentToolBroker

logger = logging.getLogger(__name__)


class CommunicationChannelType(str, Enum):
    """Communication channel type enumeration."""
    WEBSOCKET = "websocket"
    HTTP = "http"
    QUEUE = "queue"
    PUBSUB = "pubsub"
    DIRECT = "direct"


class CommunicationStatus(str, Enum):
    """Communication status enumeration."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
    RETRYING = "retrying"


class CommunicationError(Exception):
    """Exception raised for communication errors."""
    pass


class CommunicationManager:
    """
    Manager for establishing and maintaining communication channels between systems.
    
    This class provides functionality to:
    1. Create and manage communication channels between different systems
    2. Send and receive messages through these channels
    3. Handle both synchronous and asynchronous communication
    4. Manage connection pools and sessions
    5. Handle communication errors and implement retry logic
    6. Log communication events for monitoring and debugging
    
    Example usage:
        ```python
        # Initialize the communication manager
        comm_manager = CommunicationManager(
            config={
                "max_retries": 3,
                "retry_delay": 1.0,
                "connection_timeout": 30.0,
                "verbose": True
            }
        )
        
        # Create a communication channel
        channel_id = await comm_manager.create_channel(
            channel_type=CommunicationChannelType.WEBSOCKET,
            endpoint="ws://localhost:8765",
            system_id="langchain_system"
        )
        
        # Send a message through the channel
        message = AgentMessage(
            message_id="msg_123",
            sender_id="karen_system",
            recipient_id="langchain_system",
            message_type="task_request",
            content={"task": "process_data"}
        )
        await comm_manager.send_message(channel_id, message)
        
        # Receive a message from the channel
        response = await comm_manager.receive_message(channel_id, timeout=10.0)
        
        # Close the channel
        await comm_manager.close_channel(channel_id)
        ```
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        agent_validation: Optional[AgentValidation] = None,
        agent_memory: Optional[EnhancedAgentMemory] = None,
        tool_broker: Optional[AgentToolBroker] = None,
        langchain_adapter: Optional[LangChainAdapter] = None,
        deepagents_adapter: Optional[DeepAgentsAdapter] = None,
        karen_langchain_bridge: Optional[KarenLangChainBridge] = None,
        karen_deepagents_bridge: Optional[KarenDeepAgentsBridge] = None
    ):
        """
        Initialize the CommunicationManager.
        
        Args:
            config: Configuration dictionary for the communication manager
            agent_validation: Agent validation service instance
            agent_memory: Agent memory service instance
            tool_broker: Agent tool broker instance
            langchain_adapter: LangChain adapter instance
            deepagents_adapter: DeepAgents adapter instance
            karen_langchain_bridge: Karen-LangChain bridge instance
            karen_deepagents_bridge: Karen-DeepAgents bridge instance
        """
        self.config = config or {}
        self.agent_validation = agent_validation
        self.agent_memory = agent_memory
        self.tool_broker = tool_broker
        self.langchain_adapter = langchain_adapter
        self.deepagents_adapter = deepagents_adapter
        self.karen_langchain_bridge = karen_langchain_bridge
        self.karen_deepagents_bridge = karen_deepagents_bridge
        
        # Communication channels
        self._channels: Dict[str, Dict[str, Any]] = {}
        self._channel_handlers: Dict[str, Callable[[AgentMessage], Awaitable[None]]] = {}
        
        # Connection pools and sessions
        self._http_sessions: Dict[str, Any] = {}
        self._websocket_connections: Dict[str, Any] = {}
        
        # Communication configuration
        self._max_retries = self.config.get("max_retries", 3)
        self._retry_delay = self.config.get("retry_delay", 1.0)
        self._connection_timeout = self.config.get("connection_timeout", 30.0)
        self._message_timeout = self.config.get("message_timeout", 10.0)
        self._verbose = self.config.get("verbose", False)
        self._enable_error_handling = self.config.get("enable_error_handling", True)
        
        # Event loop for async operations
        self._loop = asyncio.get_event_loop()
        
        logger.info("CommunicationManager initialized successfully")
    
    async def create_channel(
        self,
        channel_type: Union[CommunicationChannelType, str],
        system_id: str,
        endpoint: Optional[str] = None,
        channel_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new communication channel between systems.
        
        Args:
            channel_type: Type of communication channel
            endpoint: Endpoint URL for the channel (if applicable)
            system_id: ID of the system to communicate with
            channel_config: Additional configuration for the channel
            
        Returns:
            Channel ID if creation was successful
            
        Raises:
            CommunicationError: If channel creation fails
            ValueError: If invalid parameters are provided
            
        Example:
            ```python
            channel_id = await comm_manager.create_channel(
                channel_type=CommunicationChannelType.WEBSOCKET,
                endpoint="ws://localhost:8765",
                system_id="langchain_system",
                channel_config={"heartbeat_interval": 30}
            )
            ```
        """
        try:
            # Validate channel type
            if isinstance(channel_type, str):
                try:
                    channel_type = CommunicationChannelType(channel_type)
                except ValueError:
                    raise ValueError(f"Invalid channel type: {channel_type}")
            
            # Generate channel ID
            channel_id = f"{system_id}_{channel_type.value}_{datetime.utcnow().timestamp()}"
            
            # Initialize channel data
            channel_data = {
                "channel_id": channel_id,
                "channel_type": channel_type,
                "endpoint": endpoint,
                "system_id": system_id,
                "config": channel_config or {},
                "status": CommunicationStatus.CONNECTING,
                "created_at": datetime.utcnow(),
                "last_activity": datetime.utcnow()
            }
            
            # Create the appropriate connection based on channel type
            if channel_type == CommunicationChannelType.WEBSOCKET:
                if not HAS_WEBSOCKETS:
                    raise CommunicationError("WebSockets library is not available")
                
                if not endpoint:
                    raise ValueError("WebSocket channels require an endpoint")
                
                # Create WebSocket connection
                try:
                    websocket = await asyncio.wait_for(
                        websockets.connect(endpoint),
                        timeout=self._connection_timeout
                    )
                    self._websocket_connections[channel_id] = websocket
                    channel_data["status"] = CommunicationStatus.CONNECTED
                    logger.info(f"WebSocket channel {channel_id} connected to {endpoint}")
                except Exception as e:
                    channel_data["status"] = CommunicationStatus.ERROR
                    channel_data["error"] = str(e)
                    logger.error(f"Failed to connect WebSocket channel {channel_id}: {e}")
                    raise CommunicationError(f"Failed to connect WebSocket: {e}")
                    
            elif channel_type == CommunicationChannelType.HTTP:
                if not HAS_AIOHTTP:
                    raise CommunicationError("aiohttp library is not available")
                
                if not endpoint:
                    raise ValueError("HTTP channels require an endpoint")
                
                # Create HTTP session
                try:
                    session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=self._connection_timeout)
                    )
                    self._http_sessions[channel_id] = session
                    channel_data["status"] = CommunicationStatus.CONNECTED
                    logger.info(f"HTTP channel {channel_id} created for {endpoint}")
                except Exception as e:
                    channel_data["status"] = CommunicationStatus.ERROR
                    channel_data["error"] = str(e)
                    logger.error(f"Failed to create HTTP channel {channel_id}: {e}")
                    raise CommunicationError(f"Failed to create HTTP session: {e}")
                    
            elif channel_type in [CommunicationChannelType.QUEUE, CommunicationChannelType.PUBSUB]:
                # For queue and pubsub channels, we just store the configuration
                # The actual connection will be established when sending/receiving messages
                channel_data["status"] = CommunicationStatus.CONNECTED
                logger.info(f"{channel_type.value} channel {channel_id} created for {system_id}")
                
            elif channel_type == CommunicationChannelType.DIRECT:
                # For direct channels, no connection is needed
                channel_data["status"] = CommunicationStatus.CONNECTED
                logger.info(f"Direct channel {channel_id} created for {system_id}")
                
            else:
                raise ValueError(f"Unsupported channel type: {channel_type}")
            
            # Store the channel
            self._channels[channel_id] = channel_data
            
            return channel_id
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error creating channel: {e}")
                logger.debug(traceback.format_exc())
            raise CommunicationError(f"Failed to create channel: {e}")
    
    async def close_channel(self, channel_id: str) -> bool:
        """
        Close an existing communication channel.
        
        Args:
            channel_id: ID of the channel to close
            
        Returns:
            True if closure was successful, False otherwise
            
        Example:
            ```python
            success = await comm_manager.close_channel("langchain_system_websocket_1234567890")
            ```
        """
        try:
            if channel_id not in self._channels:
                logger.warning(f"Channel {channel_id} not found")
                return False
            
            channel = self._channels[channel_id]
            channel_type = channel["channel_type"]
            
            # Close the appropriate connection based on channel type
            if channel_type == CommunicationChannelType.WEBSOCKET:
                if channel_id in self._websocket_connections:
                    websocket = self._websocket_connections[channel_id]
                    await websocket.close()
                    del self._websocket_connections[channel_id]
                    logger.info(f"WebSocket channel {channel_id} closed")
                    
            elif channel_type == CommunicationChannelType.HTTP:
                if channel_id in self._http_sessions:
                    session = self._http_sessions[channel_id]
                    await session.close()
                    del self._http_sessions[channel_id]
                    logger.info(f"HTTP channel {channel_id} closed")
            
            # Update channel status
            channel["status"] = CommunicationStatus.DISCONNECTED
            channel["closed_at"] = datetime.utcnow()
            
            # Remove the channel handler if it exists
            if channel_id in self._channel_handlers:
                del self._channel_handlers[channel_id]
            
            return True
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error closing channel {channel_id}: {e}")
                logger.debug(traceback.format_exc())
            return False
    
    async def send_message(
        self,
        channel_id: str,
        message: Union[AgentMessage, Dict[str, Any]],
        timeout: Optional[float] = None
    ) -> bool:
        """
        Send a message through a communication channel.
        
        Args:
            channel_id: ID of the channel to send the message through
            message: Message to send (AgentMessage or dictionary)
            timeout: Timeout for the send operation (uses default if None)
            
        Returns:
            True if the message was sent successfully, False otherwise
            
        Example:
            ```python
            message = AgentMessage(
                message_id="msg_123",
                sender_id="karen_system",
                recipient_id="langchain_system",
                message_type="task_request",
                content={"task": "process_data"}
            )
            success = await comm_manager.send_message("channel_123", message)
            ```
        """
        try:
            if channel_id not in self._channels:
                logger.error(f"Channel {channel_id} not found")
                return False
            
            channel = self._channels[channel_id]
            channel_type = channel["channel_type"]
            
            # Convert message to dictionary if it's an AgentMessage
            if isinstance(message, AgentMessage):
                message_dict = message.model_dump()
            else:
                message_dict = message
            
            # Serialize message to JSON
            message_json = json.dumps(message_dict)
            
            # Set timeout
            send_timeout = timeout or self._message_timeout
            
            # Send the message based on channel type
            if channel_type == CommunicationChannelType.WEBSOCKET:
                if channel_id not in self._websocket_connections:
                    logger.error(f"No WebSocket connection for channel {channel_id}")
                    return False
                
                websocket = self._websocket_connections[channel_id]
                try:
                    await asyncio.wait_for(
                        websocket.send(message_json),
                        timeout=send_timeout
                    )
                    logger.debug(f"Message sent via WebSocket channel {channel_id}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to send message via WebSocket channel {channel_id}: {e}")
                    return False
                    
            elif channel_type == CommunicationChannelType.HTTP:
                if channel_id not in self._http_sessions:
                    logger.error(f"No HTTP session for channel {channel_id}")
                    return False
                
                session = self._http_sessions[channel_id]
                endpoint = channel["endpoint"]
                
                try:
                    async with session.post(
                        endpoint,
                        data=message_json,
                        headers={"Content-Type": "application/json"},
                        timeout=send_timeout
                    ) as response:
                        if response.status < 400:
                            logger.debug(f"Message sent via HTTP channel {channel_id}")
                            return True
                        else:
                            logger.error(f"HTTP error sending message via channel {channel_id}: {response.status}")
                            return False
                except Exception as e:
                    logger.error(f"Failed to send message via HTTP channel {channel_id}: {e}")
                    return False
                    
            elif channel_type == CommunicationChannelType.DIRECT:
                # For direct channels, we call the handler directly
                if channel_id in self._channel_handlers:
                    try:
                        handler = self._channel_handlers[channel_id]
                        # Convert dict back to AgentMessage if needed
                        if isinstance(message_dict, dict):
                            try:
                                message_obj = AgentMessage(**message_dict)
                                await handler(message_obj)
                            except Exception as e:
                                logger.error(f"Error converting message dict to AgentMessage: {e}")
                                # Pass the original dict to the handler
                                await handler(AgentMessage(**message_dict))
                        else:
                            await handler(message_dict)
                        logger.debug(f"Message sent via direct channel {channel_id}")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to send message via direct channel {channel_id}: {e}")
                        return False
                else:
                    logger.warning(f"No handler registered for direct channel {channel_id}")
                    return False
                    
            else:
                logger.error(f"Sending messages via {channel_type.value} channels is not implemented")
                return False
                
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error sending message via channel {channel_id}: {e}")
                logger.debug(traceback.format_exc())
            return False
    
    async def receive_message(
        self,
        channel_id: str,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Receive a message from a communication channel.
        
        Args:
            channel_id: ID of the channel to receive the message from
            timeout: Timeout for the receive operation (uses default if None)
            
        Returns:
            Received message as a dictionary, or None if no message was received
            
        Example:
            ```python
            message = await comm_manager.receive_message("channel_123", timeout=5.0)
            if message:
                print(f"Received message: {message}")
            ```
        """
        try:
            if channel_id not in self._channels:
                logger.error(f"Channel {channel_id} not found")
                return None
            
            channel = self._channels[channel_id]
            channel_type = channel["channel_type"]
            
            # Set timeout
            receive_timeout = timeout or self._message_timeout
            
            # Receive the message based on channel type
            if channel_type == CommunicationChannelType.WEBSOCKET:
                if channel_id not in self._websocket_connections:
                    logger.error(f"No WebSocket connection for channel {channel_id}")
                    return None
                
                websocket = self._websocket_connections[channel_id]
                try:
                    message_json = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=receive_timeout
                    )
                    message_dict = json.loads(message_json)
                    logger.debug(f"Message received via WebSocket channel {channel_id}")
                    return message_dict
                except Exception as e:
                    logger.error(f"Failed to receive message via WebSocket channel {channel_id}: {e}")
                    return None
                    
            elif channel_type == CommunicationChannelType.HTTP:
                # HTTP channels don't typically receive messages this way
                # They would use a webhook or similar mechanism
                logger.error(f"HTTP channels don't support direct message receiving")
                return None
                    
            else:
                logger.error(f"Receiving messages via {channel_type.value} channels is not implemented")
                return None
                
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error receiving message via channel {channel_id}: {e}")
                logger.debug(traceback.format_exc())
            return None
    
    async def broadcast_message(
        self,
        message: Union[AgentMessage, Dict[str, Any]],
        channel_ids: Optional[List[str]] = None,
        system_ids: Optional[List[str]] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, bool]:
        """
        Send a message to multiple channels.
        
        Args:
            message: Message to send
            channel_ids: List of specific channel IDs to send to (if None, sends to all matching channels)
            system_ids: List of system IDs to send to (only used if channel_ids is None)
            timeout: Timeout for each send operation
            
        Returns:
            Dictionary mapping channel IDs to success status
            
        Example:
            ```python
            message = AgentMessage(
                message_id="msg_123",
                sender_id="karen_system",
                recipient_id="all",
                message_type="broadcast",
                content={"announcement": "System maintenance at 10 PM"}
            )
            results = await comm_manager.broadcast_message(
                message, 
                system_ids=["langchain_system", "deepagents_system"]
            )
            ```
        """
        try:
            # Determine target channels
            target_channels = []
            
            if channel_ids:
                # Use specific channel IDs
                for channel_id in channel_ids:
                    if channel_id in self._channels:
                        target_channels.append(channel_id)
                    else:
                        logger.warning(f"Channel {channel_id} not found for broadcast")
            elif system_ids:
                # Find channels for the specified system IDs
                for channel_id, channel in self._channels.items():
                    if channel["system_id"] in system_ids:
                        target_channels.append(channel_id)
            else:
                # Send to all channels
                target_channels = list(self._channels.keys())
            
            # Send the message to each target channel
            results = {}
            for channel_id in target_channels:
                success = await self.send_message(channel_id, message, timeout)
                results[channel_id] = success
            
            return results
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error broadcasting message: {e}")
                logger.debug(traceback.format_exc())
            return {}
    
    async def register_handler(
        self,
        channel_id: str,
        handler: Callable[[AgentMessage], Awaitable[None]]
    ) -> bool:
        """
        Register a message handler for a specific channel.
        
        Args:
            channel_id: ID of the channel to register the handler for
            handler: Async function that handles incoming messages
            
        Returns:
            True if registration was successful, False otherwise
            
        Example:
            ```python
            async def message_handler(message: AgentMessage):
                print(f"Received message: {message.content}")
                # Process the message...
                
            success = await comm_manager.register_handler("channel_123", message_handler)
            ```
        """
        try:
            if channel_id not in self._channels:
                logger.error(f"Channel {channel_id} not found")
                return False
            
            # Store the handler
            self._channel_handlers[channel_id] = handler
            logger.info(f"Message handler registered for channel {channel_id}")
            return True
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error registering handler for channel {channel_id}: {e}")
                logger.debug(traceback.format_exc())
            return False
    
    async def communicate_with_langchain(
        self,
        task: AgentTask,
        channel_config: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        """
        Establish communication with LangChain agents.
        
        Args:
            task: Task to send to LangChain
            channel_config: Configuration for the communication channel
            
        Returns:
            Response from LangChain
            
        Example:
            ```python
            task = AgentTask(
                task_id="task_123",
                agent_id="karen_agent",
                task_type="text_generation",
                description="Generate a summary of the provided text",
                input_data={"text": "Long text to summarize..."}
            )
            response = await comm_manager.communicate_with_langchain(task)
            ```
        """
        try:
            # Check if LangChain adapter is available
            if not self.langchain_adapter:
                # Try to use the Karen-LangChain bridge if available
                if not self.karen_langchain_bridge:
                    raise CommunicationError("Neither LangChain adapter nor Karen-LangChain bridge is available")
                
                # Use the bridge to execute the task
                return await self.karen_langchain_bridge.execute_agent("langchain_agent", task)
            
            # Create a communication channel if needed
            channel_id = None
            if channel_config:
                channel_id = await self.create_channel(
                    channel_type=CommunicationChannelType.DIRECT,
                    system_id="langchain_system",
                    channel_config=channel_config
                )
            
            # Execute the task using the LangChain adapter
            response = await self.langchain_adapter.execute_agent("langchain_agent", task)
            
            # Close the channel if we created one
            if channel_id:
                await self.close_channel(channel_id)
            
            return response
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error communicating with LangChain: {e}")
                logger.debug(traceback.format_exc())
            return AgentResponse(
                response_id=f"resp_{task.task_id}",
                task_id=task.task_id,
                agent_id="langchain_agent",
                success=False,
                data={},
                error=str(e),
                execution_time=0.0
            )
    
    async def communicate_with_deepagents(
        self,
        task: AgentTask,
        channel_config: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        """
        Establish communication with DeepAgents.
        
        Args:
            task: Task to send to DeepAgents
            channel_config: Configuration for the communication channel
            
        Returns:
            Response from DeepAgents
            
        Example:
            ```python
            task = AgentTask(
                task_id="task_123",
                agent_id="karen_agent",
                task_type="reasoning",
                description="Analyze the logical consistency of the argument",
                input_data={"argument": "Premise: All men are mortal. Socrates is a man. Conclusion: Socrates is mortal."}
            )
            response = await comm_manager.communicate_with_deepagents(task)
            ```
        """
        try:
            # Check if DeepAgents adapter is available
            if not self.deepagents_adapter:
                # Try to use the Karen-DeepAgents bridge if available
                if not self.karen_deepagents_bridge:
                    raise CommunicationError("Neither DeepAgents adapter nor Karen-DeepAgents bridge is available")
                
                # Use the bridge to execute the task
                return await self.karen_deepagents_bridge.execute_agent("deepagent", task)
            
            # Create a communication channel if needed
            channel_id = None
            if channel_config:
                channel_id = await self.create_channel(
                    channel_type=CommunicationChannelType.DIRECT,
                    system_id="deepagents_system",
                    channel_config=channel_config
                )
            
            # Execute the task using the DeepAgents adapter
            response = await self.deepagents_adapter.execute_task("deepagent", task)
            
            # Close the channel if we created one
            if channel_id:
                await self.close_channel(channel_id)
            
            return response
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error communicating with DeepAgents: {e}")
                logger.debug(traceback.format_exc())
            return AgentResponse(
                response_id=f"resp_{task.task_id}",
                task_id=task.task_id,
                agent_id="deepagent",
                success=False,
                data={},
                error=str(e),
                execution_time=0.0
            )
    
    async def communicate_with_karen(
        self,
        message: AgentMessage,
        channel_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Establish communication with Karen's system.
        
        Args:
            message: Message to send to Karen's system
            channel_config: Configuration for the communication channel
            
        Returns:
            True if communication was successful, False otherwise
            
        Example:
            ```python
            message = AgentMessage(
                message_id="msg_123",
                sender_id="external_agent",
                recipient_id="karen_system",
                message_type="data_request",
                content={"query": "user_preferences"}
            )
            success = await comm_manager.communicate_with_karen(message)
            ```
        """
        try:
            # Create a communication channel if needed
            channel_id = None
            if channel_config:
                channel_id = await self.create_channel(
                    channel_type=CommunicationChannelType.DIRECT,
                    system_id="karen_system",
                    channel_config=channel_config
                )
            
            # Send the message to Karen's system
            # This would typically involve sending to a specific endpoint or handler
            # For now, we'll just log the message
            logger.info(f"Sending message to Karen's system: {message.message_id}")
            logger.debug(f"Message content: {message.content}")
            
            # Close the channel if we created one
            if channel_id:
                await self.close_channel(channel_id)
            
            return True
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error communicating with Karen's system: {e}")
                logger.debug(traceback.format_exc())
            return False
    
    async def communicate_with_memory(
        self,
        memory_request: Dict[str, Any],
        channel_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Establish communication with the memory system.
        
        Args:
            memory_request: Request to send to the memory system
            channel_config: Configuration for the communication channel
            
        Returns:
            Response from the memory system
            
        Example:
            ```python
            request = {
                "operation": "retrieve",
                "agent_id": "agent_123",
                "query": "previous conversations about AI ethics",
                "limit": 10
            }
            response = await comm_manager.communicate_with_memory(request)
            ```
        """
        try:
            # Check if agent memory service is available
            if not self.agent_memory:
                raise CommunicationError("Agent memory service is not available")
            
            # Create a communication channel if needed
            channel_id = None
            if channel_config:
                channel_id = await self.create_channel(
                    channel_type=CommunicationChannelType.DIRECT,
                    system_id="memory_system",
                    channel_config=channel_config
                )
            
            # Process the memory request
            operation = memory_request.get("operation", "retrieve")
            agent_id = memory_request.get("agent_id")
            
            if operation == "retrieve":
                # Retrieve memories
                if agent_id is None:
                    raise ValueError("agent_id is required for memory operations")
                    
                memories = await self.agent_memory.list_memories(
                    agent_id=agent_id,
                    limit=memory_request.get("limit", 10),
                    include_shared=memory_request.get("include_shared", False)
                )
                response = {"memories": memories}
                
            elif operation == "store":
                # Store a memory
                memory_data = memory_request.get("memory", {})
                memory = AgentMemory(
                    memory_id=memory_data.get("memory_id", f"mem_{datetime.utcnow().timestamp()}"),
                    agent_id=agent_id,
                    content=memory_data.get("content", {}),
                    tags=memory_data.get("tags", []),
                    importance=memory_data.get("importance", 0.5)
                )
                if agent_id is None:
                    raise ValueError("agent_id is required for memory operations")
                    
                # Use the correct method signature for store_memory
                success = await self.agent_memory.store_memory(
                    agent_id=agent_id,
                    memory_type=memory.get("memory_type", "general"),
                    content=memory.get("content", {})
                )
                response = {"success": success}
                
            elif operation == "update":
                # Update a memory
                memory_id = memory_request.get("memory_id")
                updates = memory_request.get("updates", {})
                if memory_id is None:
                    raise ValueError("memory_id is required for update_memory operation")
                    
                success = await self.agent_memory.update_memory(memory_id, updates)
                response = {"success": success}
                
            elif operation == "delete":
                # Delete a memory
                memory_id = memory_request.get("memory_id")
                if memory_id is None:
                    raise ValueError("memory_id is required for delete_memory operation")
                    
                success = await self.agent_memory.delete_memory(memory_id)
                response = {"success": success}
                
            else:
                raise ValueError(f"Unsupported memory operation: {operation}")
            
            # Close the channel if we created one
            if channel_id:
                await self.close_channel(channel_id)
            
            return response
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error communicating with memory system: {e}")
                logger.debug(traceback.format_exc())
            return {"error": str(e)}
    
    async def communicate_with_tools(
        self,
        tool_request: Dict[str, Any],
        channel_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Establish communication with the tool system.
        
        Args:
            tool_request: Request to send to the tool system
            channel_config: Configuration for the communication channel
            
        Returns:
            Response from the tool system
            
        Example:
            ```python
            request = {
                "operation": "execute",
                "agent_id": "agent_123",
                "tool_id": "calculator",
                "parameters": {"expression": "2 + 2"}
            }
            response = await comm_manager.communicate_with_tools(request)
            ```
        """
        try:
            # Check if tool broker is available
            if not self.tool_broker:
                raise CommunicationError("Tool broker is not available")
            
            # Create a communication channel if needed
            channel_id = None
            if channel_config:
                channel_id = await self.create_channel(
                    channel_type=CommunicationChannelType.DIRECT,
                    system_id="tool_system",
                    channel_config=channel_config
                )
            
            # Process the tool request
            operation = tool_request.get("operation", "execute")
            agent_id = tool_request.get("agent_id")
            
            if operation == "execute":
                # Execute a tool
                tool_id = tool_request.get("tool_id")
                parameters = tool_request.get("parameters", {})
                if agent_id is None or tool_id is None:
                    raise ValueError("agent_id and tool_id are required for execute_tool operation")
                    
                result = await self.tool_broker.execute_tool(
                    agent_id=agent_id,
                    tool_id=tool_id,
                    parameters=parameters
                )
                response = {"result": result}
                
            elif operation == "list":
                # List available tools
                if agent_id is None:
                    raise ValueError("agent_id is required for get_agent_tools operation")
                    
                tools = await self.tool_broker.get_agent_tools(agent_id)
                response = {"tools": tools}
                
            elif operation == "check_access":
                # Check access to a tool
                tool_id = tool_request.get("tool_id")
                if agent_id is None or tool_id is None:
                    raise ValueError("agent_id and tool_id are required for check_tool_access operation")
                    
                # Use check_access instead of has_tool_access
                # Check if agent has access to the tool
                if agent_id in self.tool_broker._agent_permissions and tool_id in self.tool_broker._agent_permissions[agent_id]:
                    access_decision = "allow"
                else:
                    access_decision = "deny"
                response = {"access_decision": access_decision}
                
            else:
                raise ValueError(f"Unsupported tool operation: {operation}")
            
            # Close the channel if we created one
            if channel_id:
                await self.close_channel(channel_id)
            
            return response
            
        except Exception as e:
            if self._enable_error_handling:
                logger.error(f"Error communicating with tool system: {e}")
                logger.debug(traceback.format_exc())
            return {"error": str(e)}
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the communication manager.
        
        Returns:
            Health status information
            
        Example:
            ```python
            health = await comm_manager.health_check()
            print(f"Communication manager status: {health['status']}")
            ```
        """
        try:
            # Count channels by status
            channels_by_status = {}
            for channel in self._channels.values():
                status = channel["status"]
                if status not in channels_by_status:
                    channels_by_status[status] = 0
                channels_by_status[status] += 1
            
            # Count channels by type
            channels_by_type = {}
            for channel in self._channels.values():
                channel_type = channel["channel_type"]
                if channel_type not in channels_by_type:
                    channels_by_type[channel_type] = 0
                channels_by_type[channel_type] += 1
            
            # Check dependencies
            dependencies = {
                "websockets_available": HAS_WEBSOCKETS,
                "aiohttp_available": HAS_AIOHTTP,
                "langchain_adapter_available": self.langchain_adapter is not None,
                "deepagents_adapter_available": self.deepagents_adapter is not None,
                "karen_langchain_bridge_available": self.karen_langchain_bridge is not None,
                "karen_deepagents_bridge_available": self.karen_deepagents_bridge is not None,
                "agent_validation_available": self.agent_validation is not None,
                "agent_memory_available": self.agent_memory is not None,
                "tool_broker_available": self.tool_broker is not None
            }
            
            return {
                "service": "communication_manager",
                "timestamp": datetime.utcnow().isoformat(),
                "status": "healthy",
                "total_channels": len(self._channels),
                "channels_by_status": channels_by_status,
                "channels_by_type": channels_by_type,
                "active_websocket_connections": len(self._websocket_connections),
                "active_http_sessions": len(self._http_sessions),
                "registered_handlers": len(self._channel_handlers),
                "dependencies": dependencies,
                "configuration": {
                    "max_retries": self._max_retries,
                    "retry_delay": self._retry_delay,
                    "connection_timeout": self._connection_timeout,
                    "message_timeout": self._message_timeout,
                    "enable_error_handling": self._enable_error_handling
                }
            }
            
        except Exception as e:
            logger.error(f"Error during health check: {e}")
            return {
                "service": "communication_manager",
                "timestamp": datetime.utcnow().isoformat(),
                "status": "error",
                "error": str(e)
            }
    
    async def shutdown(self) -> None:
        """
        Shutdown the communication manager and close all connections.
        
        Example:
            ```python
            await comm_manager.shutdown()
            ```
        """
        try:
            logger.info("Shutting down CommunicationManager")
            
            # Close all WebSocket connections
            for channel_id, websocket in self._websocket_connections.items():
                try:
                    await websocket.close()
                    logger.debug(f"Closed WebSocket connection for channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error closing WebSocket connection for channel {channel_id}: {e}")
            
            # Close all HTTP sessions
            for channel_id, session in self._http_sessions.items():
                try:
                    await session.close()
                    logger.debug(f"Closed HTTP session for channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error closing HTTP session for channel {channel_id}: {e}")
            
            # Clear all data structures
            self._channels.clear()
            self._channel_handlers.clear()
            self._websocket_connections.clear()
            self._http_sessions.clear()
            
            logger.info("CommunicationManager shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            logger.debug(traceback.format_exc())
