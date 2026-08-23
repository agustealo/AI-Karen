"""
Execution Mode Handlers for Agent Integration

This module implements handlers for different agent execution modes:
- Native: Direct LLM execution
- LangGraph: Graph-based orchestration
- DeepAgents: Advanced multi-agent system
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional

from .models import (
    AgentConfig,
    AgentError,
    AgentExecutionMode,
    AgentRequest,
    AgentResponse,
    AgentStatus,
    StreamChunk,
    AgentCapability
)

logger = logging.getLogger(__name__)


def _get_model_manager():
    """Lazy import to avoid circular dependency."""
    from ai_karen_engine.core.model_runtime.model_manager import ModelManager
    return ModelManager


class BaseExecutionHandler(ABC):
    """Base class for execution handlers."""
    
    def __init__(self, execution_mode: AgentExecutionMode):
        self.execution_mode = execution_mode
        self.logger = logging.getLogger(f"{__name__}.{execution_mode}")
    
    @abstractmethod
    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute a request synchronously."""
        pass
    
    @abstractmethod
    async def execute_stream(self, request: AgentRequest) -> AsyncGenerator[StreamChunk, None]:
        """Execute a request with streaming response."""
        pass
    
    @abstractmethod
    async def validate_capabilities(self, capabilities: List[AgentCapability]) -> bool:
        """Validate if the handler supports the required capabilities."""
        pass
    
    @abstractmethod
    async def get_status(self) -> AgentStatus:
        """Get the current status of the execution handler."""
        pass
    
    def create_error_response(
        self, 
        request: AgentRequest, 
        error: Exception, 
        recoverable: bool = True
    ) -> AgentResponse:
        """Create an error response."""
        return AgentResponse(
            request_id=request.request_id,
            agent_id=request.agent_id or "unknown",
            execution_mode=self.execution_mode,
            response="",
            processing_time=0.0,
            error=AgentError(
                code="EXECUTION_ERROR",
                message=str(error),
                recoverable=recoverable,
                details={"exception_type": type(error).__name__}
            )
        )


class NativeExecutionHandler(BaseExecutionHandler):
    """Handler for native LLM execution."""
    
    def __init__(self):
        super().__init__(AgentExecutionMode.NATIVE)
        self._status = AgentStatus.IDLE
        self._supported_capabilities = {
            AgentCapability.TEXT_GENERATION,
            AgentCapability.CODE_GENERATION,
            AgentCapability.ANALYSIS,
            AgentCapability.REASONING,
            AgentCapability.STREAMING
        }
    
    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute request using native LLM."""
        start_time = datetime.utcnow()
        
        try:
            self._status = AgentStatus.PROCESSING
            self.logger.info(f"Executing native request: {request.request_id}")
            
            # Import here to avoid circular imports
            from ai_karen_engine.integrations.llm_registry import get_registry
            
            # Get LLM registry and provider
            registry = get_registry()
            
            # Prepare routing context
            routing_context = {
                "user_id": request.user_id,
                "session_id": request.session_id,
                "task_type": "chat",
                "capabilities": [cap.value for cap in request.capabilities_required]
            }
            
            # Get appropriate provider
            provider_result = await registry.get_provider_with_routing(
                user_ctx=routing_context,
                query=request.message,
                task_type="chat",
                khrp_step="agent_execution",
                requirements={}
            )
            
            if not provider_result or "provider" not in provider_result:
                raise Exception("No suitable provider found for native execution")
            
            provider = provider_result["provider"]
            
            # Execute the request
            response_text = await _get_model_manager().invoke_provider(
                provider,
                request.message,
                context=request.context or {},
                config=request.config.custom_config if request.config else {},
            )
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "native_agent",
                execution_mode=self.execution_mode,
                response=response_text,
                processing_time=processing_time,
                capabilities_used=request.capabilities_required,
                metadata={
                    "provider": provider_result.get("decision", {}).get("provider"),
                    "model": provider_result.get("decision", {}).get("model"),
                    "routing_confidence": provider_result.get("decision", {}).get("confidence")
                }
            )
            
        except Exception as e:
            self.logger.error(f"Native execution error: {e}")
            self._status = AgentStatus.ERROR
            return self.create_error_response(request, e)
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def execute_stream(self, request: AgentRequest) -> AsyncIterator[StreamChunk]:
        """Execute request with streaming using native LLM via OrchestrationAgent."""
        try:
            self._status = AgentStatus.STREAMING
            self.logger.info(f"Starting native stream: {request.request_id}")
            
            # Import here to avoid circular imports
            from ai_karen_engine.services.orchestration.orchestration_agent import get_orchestration_agent, OrchestrationInput
            
            # Get orchestration agent
            agent = get_orchestration_agent()
            
            # Create orchestration input
            orchestration_input = OrchestrationInput(
                message=request.message,
                conversation_history=request.conversation_history,
                session_id=request.session_id,
                user_id=request.user_id,
                context=request.context,
                llm_preferences=request.context.get("llm_preferences") if request.context else None
            )
            
            # Execute through orchestration agent streaming method
            async for chunk in agent.orchestrate_stream(orchestration_input):
                yield StreamChunk(
                    content=chunk,
                    chunk_type="text",
                    metadata={"orchestrator": "native"}
                )
            
            # Send final chunk
            yield StreamChunk(
                content="",
                chunk_type="metadata",
                is_final=True,
                metadata={
                    "orchestrator": "native",
                    "complete": True
                }
            )
            
        except Exception as e:
            self.logger.error(f"Native streaming error: {e}")
            self._status = AgentStatus.ERROR
            yield StreamChunk(
                content=f"Streaming error: {str(e)}",
                chunk_type="error",
                metadata={"error": str(e)}
            )
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def validate_capabilities(self, capabilities: List[AgentCapability]) -> bool:
        """Validate native handler capabilities."""
        return all(cap in self._supported_capabilities for cap in capabilities)
    
    async def get_status(self) -> AgentStatus:
        """Get current status."""
        return self._status


class LangGraphExecutionHandler(BaseExecutionHandler):
    """Handler for LangGraph orchestration."""
    
    def __init__(self):
        super().__init__(AgentExecutionMode.LANGGRAPH)
        self._status = AgentStatus.IDLE
        self._supported_capabilities = {
            AgentCapability.TEXT_GENERATION,
            AgentCapability.CODE_GENERATION,
            AgentCapability.ANALYSIS,
            AgentCapability.REASONING,
            AgentCapability.MEMORY_ACCESS,
            AgentCapability.TOOL_USE,
            AgentCapability.STREAMING
        }
    
    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute request using LangGraph orchestration."""
        start_time = datetime.utcnow()
        
        try:
            self._status = AgentStatus.PROCESSING
            self.logger.info(f"Executing LangGraph request: {request.request_id}")
            
            # Import here to avoid circular imports
            from ..core.langgraph_orchestrator import get_default_orchestrator
            from langchain_core.messages import HumanMessage
            
            # Get LangGraph orchestrator
            orchestrator = get_default_orchestrator()
            
            # Convert message to LangChain format
            messages = [HumanMessage(content=request.message)]
            
            # Process through orchestration
            result = await orchestrator.process(
                messages=messages,
                user_id=request.user_id or "anonymous",
                session_id=request.session_id,
                config=request.config.custom_config if request.config else {}
            )
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            response_text = result.get("response", "I apologize, but I couldn't generate a response.")
            
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "langgraph_agent",
                execution_mode=self.execution_mode,
                response=response_text,
                processing_time=processing_time,
                capabilities_used=request.capabilities_required,
                metadata={
                    "orchestrator": "langgraph",
                    "response_metadata": result.get("response_metadata", {}),
                    "errors": result.get("errors", []),
                    "warnings": result.get("warnings", [])
                },
                warnings=result.get("warnings", [])
            )
            
        except Exception as e:
            self.logger.error(f"LangGraph execution error: {e}")
            self._status = AgentStatus.ERROR
            return self.create_error_response(request, e)
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def execute_stream(self, request: AgentRequest) -> AsyncGenerator[StreamChunk, None]:
        """Execute request with streaming using LangGraph."""
        try:
            self._status = AgentStatus.STREAMING
            self.logger.info(f"Starting LangGraph stream: {request.request_id}")
            
            # Import here to avoid circular imports
            from langchain_core.messages import HumanMessage
            from ..core.langgraph_orchestrator import get_default_orchestrator

            orchestrator = get_default_orchestrator()
            messages = [HumanMessage(content=request.message)]

            async for chunk in orchestrator.stream_process(
                messages=messages,
                user_id=request.user_id or "anonymous",
                session_id=request.session_id,
                config=request.config.custom_config if request.config else {},
            ):
                chunk_type = "text"
                content = ""
                metadata = {}

                if isinstance(chunk, dict):
                    for state_update in chunk.values():
                        if not isinstance(state_update, dict):
                            continue
                        if "formatted_response" in state_update:
                            content = str(state_update.get("formatted_response") or "")
                            metadata = state_update.get("response_metadata") or {}
                        elif "llm_response" in state_update:
                            content = str(state_update.get("llm_response") or "")
                            metadata = state_update.get("response_metadata") or {}
                        elif "error" in state_update:
                            chunk_type = "error"
                            content = str(state_update.get("error") or "")
                            metadata = {"error": state_update.get("error")}
                elif hasattr(chunk, "content"):
                    content = str(getattr(chunk, "content") or "")
                    metadata = getattr(chunk, "metadata") or {}
                elif isinstance(chunk, str):
                    content = chunk

                if content or metadata:
                    if metadata.get("status") and not content:
                        chunk_type = "metadata"
                    yield StreamChunk(
                        content=content,
                        chunk_type=chunk_type,
                        metadata=metadata,
                    )
            
            # Send final chunk
            yield StreamChunk(
                content="",
                chunk_type="metadata",
                is_final=True,
                metadata={"orchestrator": "langgraph", "complete": True}
            )
            
        except Exception as e:
            self.logger.error(f"LangGraph streaming error: {e}")
            self._status = AgentStatus.ERROR
            yield StreamChunk(
                content=f"Streaming error: {str(e)}",
                chunk_type="error",
                metadata={"error": str(e)}
            )
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def validate_capabilities(self, capabilities: List[AgentCapability]) -> bool:
        """Validate LangGraph handler capabilities."""
        return all(cap in self._supported_capabilities for cap in capabilities)
    
    async def get_status(self) -> AgentStatus:
        """Get current status."""
        return self._status


class DeepAgentsExecutionHandler(BaseExecutionHandler):
    """Handler for DeepAgents multi-agent system."""
    
    def __init__(self):
        super().__init__(AgentExecutionMode.DEEP_AGENTS)
        self._status = AgentStatus.IDLE
        self._supported_capabilities = {
            AgentCapability.TEXT_GENERATION,
            AgentCapability.CODE_GENERATION,
            AgentCapability.ANALYSIS,
            AgentCapability.REASONING,
            AgentCapability.MEMORY_ACCESS,
            AgentCapability.TOOL_USE,
            AgentCapability.MULTIMODAL,
            AgentCapability.STREAMING
        }
    
    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute request using DeepAgents system."""
        start_time = datetime.utcnow()
        
        try:
            self._status = AgentStatus.PROCESSING
            self.logger.info(f"Executing DeepAgents request: {request.request_id}")
            
            # Import here to avoid circular imports
            from ai_karen_engine.services.orchestration.orchestration_agent import get_orchestration_agent, OrchestrationInput
            
            # Get orchestration agent
            agent = get_orchestration_agent()
            
            # Create orchestration input
            orchestration_input = OrchestrationInput(
                message=request.message,
                conversation_history=request.conversation_history,
                session_id=request.session_id,
                user_id=request.user_id,
                context=request.context
            )
            
            # Execute through orchestration agent
            envelope = await agent.orchestrate_response(orchestration_input)
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Extract response from envelope
            response_text = envelope.get("final", "No response generated")
            
            return AgentResponse(
                request_id=request.request_id,
                agent_id=request.agent_id or "deep_agents_agent",
                execution_mode=self.execution_mode,
                response=response_text,
                processing_time=processing_time,
                capabilities_used=request.capabilities_required,
                metadata={
                    "orchestrator": "deep_agents",
                    "envelope": envelope,
                    "suggestions": envelope.get("suggestions", []),
                    "alerts": envelope.get("alerts", [])
                },
                confidence=envelope.get("meta", {}).get("confidence"),
                warnings=envelope.get("alerts", [])
            )
            
        except Exception as e:
            self.logger.error(f"DeepAgents execution error: {e}")
            self._status = AgentStatus.ERROR
            return self.create_error_response(request, e)
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def execute_stream(self, request: AgentRequest) -> AsyncIterator[StreamChunk]:
        """Execute request with streaming using DeepAgents."""
        try:
            self._status = AgentStatus.STREAMING
            self.logger.info(f"Starting DeepAgents stream: {request.request_id}")
            
            # Import here to avoid circular imports
            from ai_karen_engine.services.orchestration.orchestration_agent import get_orchestration_agent, OrchestrationInput
            
            # Get orchestration agent
            agent = get_orchestration_agent()
            
            # Create orchestration input
            orchestration_input = OrchestrationInput(
                message=request.message,
                conversation_history=request.conversation_history,
                session_id=request.session_id,
                user_id=request.user_id,
                context=request.context,
                llm_preferences=request.context.get("llm_preferences") if request.context else None
            )
            
            # Execute through orchestration agent streaming method
            async for chunk in agent.orchestrate_stream(orchestration_input):
                yield StreamChunk(
                    content=chunk,
                    chunk_type="text",
                    metadata={"orchestrator": "deep_agents"}
                )
            
            # Send final chunk
            yield StreamChunk(
                content="",
                chunk_type="metadata",
                is_final=True,
                metadata={
                    "orchestrator": "deep_agents",
                    "complete": True
                }
            )
            
        except Exception as e:
            self.logger.error(f"DeepAgents streaming error: {e}")
            self._status = AgentStatus.ERROR
            yield StreamChunk(
                content=f"Streaming error: {str(e)}",
                chunk_type="error",
                metadata={"error": str(e)}
            )
        
        finally:
            self._status = AgentStatus.IDLE
    
    async def validate_capabilities(self, capabilities: List[AgentCapability]) -> bool:
        """Validate DeepAgents handler capabilities."""
        return all(cap in self._supported_capabilities for cap in capabilities)
    
    async def get_status(self) -> AgentStatus:
        """Get current status."""
        return self._status


# Handler factory and registry
_execution_handlers: Dict[AgentExecutionMode, BaseExecutionHandler] = {}


def get_execution_handler(execution_mode: AgentExecutionMode) -> BaseExecutionHandler:
    """Get execution handler for the specified mode."""
    if execution_mode not in _execution_handlers:
        if execution_mode == AgentExecutionMode.NATIVE:
            _execution_handlers[execution_mode] = NativeExecutionHandler()
        elif execution_mode == AgentExecutionMode.LANGGRAPH:
            _execution_handlers[execution_mode] = LangGraphExecutionHandler()
        elif execution_mode == AgentExecutionMode.DEEP_AGENTS:
            _execution_handlers[execution_mode] = DeepAgentsExecutionHandler()
        else:
            raise ValueError(f"Unsupported execution mode: {execution_mode}")
    
    return _execution_handlers[execution_mode]


async def validate_execution_mode_capabilities(
    execution_mode: AgentExecutionMode,
    capabilities: List[AgentCapability]
) -> bool:
    """Validate if an execution mode supports the required capabilities."""
    try:
        handler = get_execution_handler(execution_mode)
        return await handler.validate_capabilities(capabilities)
    except Exception as e:
        logger.error(f"Error validating capabilities for {execution_mode}: {e}")
        return False


async def get_all_handler_statuses() -> Dict[AgentExecutionMode, AgentStatus]:
    """Get statuses of all execution handlers."""
    statuses = {}
    for mode in AgentExecutionMode:
        try:
            handler = get_execution_handler(mode)
            statuses[mode] = await handler.get_status()
        except Exception as e:
            logger.error(f"Error getting status for {mode}: {e}")
            statuses[mode] = AgentStatus.ERROR
    return statuses
