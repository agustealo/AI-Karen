"""
Data models for Agent Integration System

.. deprecated::
    Legacy agent models are deprecated. Use ``ai_karen_engine.agent_medusa.contracts``
    for canonical runtime contracts.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4
import warnings

warnings.warn(
    "ai_karen_engine.agents.models is deprecated. "
    "Use ai_karen_engine.agent_medusa.contracts instead.",
    DeprecationWarning,
    stacklevel=2,
)

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field, field_validator


class AgentExecutionMode(str, Enum):
    """Supported agent execution modes."""
    NATIVE = "native"
    LANGGRAPH = "langgraph"
    DEEP_AGENTS = "deep_agents"


class AgentStatus(str, Enum):
    """Agent lifecycle status."""
    INITIALIZING = "initializing"
    IDLE = "idle"
    PROCESSING = "processing"
    STREAMING = "streaming"
    ERROR = "error"
    TERMINATED = "terminated"


class AgentCapability(str, Enum):
    """Available agent capabilities."""
    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"
    ANALYSIS = "analysis"
    REASONING = "reasoning"
    MEMORY_ACCESS = "memory_access"
    TOOL_USE = "tool_use"
    MULTIMODAL = "multimodal"
    STREAMING = "streaming"


class AgentError(BaseModel):
    """Agent error information."""
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Error timestamp")
    recoverable: bool = Field(True, description="Whether the error is recoverable")


class StreamChunk(BaseModel):
    """Streaming response chunk."""
    chunk_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique chunk identifier")
    content: str = Field(..., description="Chunk content")
    chunk_type: str = Field("text", description="Type of chunk (text, metadata, error, etc.)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Chunk metadata")
    is_final: bool = Field(False, description="Whether this is the final chunk")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Chunk timestamp")


class AgentConfig(BaseModel):
    """Agent configuration."""
    model_config = ConfigDict(frozen=True)
    
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    model_name: Optional[str] = Field(None, description="Model name to use")
    provider: Optional[str] = Field(None, description="Provider to use")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0, description="Temperature for generation")
    max_tokens: Optional[int] = Field(2048, ge=1, description="Maximum tokens to generate")
    timeout_seconds: Optional[int] = Field(60, ge=1, description="Timeout in seconds")
    enable_streaming: bool = Field(False, description="Enable streaming responses")
    capabilities: List[AgentCapability] = Field(default_factory=list, description="Required capabilities")
    custom_config: Dict[str, Any] = Field(default_factory=dict, description="Custom configuration")
    
    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 2.0):
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return v
    
    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("Max tokens must be at least 1")
        return v


class AgentMetrics(BaseModel):
    """Agent performance metrics."""
    agent_id: str = Field(..., description="Agent identifier")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    total_requests: int = Field(0, ge=0, description="Total requests processed")
    successful_requests: int = Field(0, ge=0, description="Successful requests")
    failed_requests: int = Field(0, ge=0, description="Failed requests")
    average_response_time: float = Field(0.0, ge=0.0, description="Average response time in seconds")
    last_request_time: Optional[datetime] = Field(None, description="Last request timestamp")
    uptime_seconds: float = Field(0.0, ge=0.0, description="Agent uptime in seconds")
    memory_usage_mb: Optional[float] = Field(None, ge=0.0, description="Memory usage in MB")
    cpu_usage_percent: Optional[float] = Field(None, ge=0.0, le=100.0, description="CPU usage percentage")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.successful_requests / total
    
    @property
    def error_rate(self) -> float:
        """Calculate error rate."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.failed_requests / total


class AgentLifecycleEvent(BaseModel):
    """Agent lifecycle event."""
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique event identifier")
    agent_id: str = Field(..., description="Agent identifier")
    event_type: str = Field(..., description="Event type")
    status_from: Optional[AgentStatus] = Field(None, description="Previous status")
    status_to: Optional[AgentStatus] = Field(None, description="New status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Event metadata")


class AgentRequest(BaseModel):
    """Agent execution request."""
    request_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique request identifier")
    agent_id: Optional[str] = Field(None, description="Target agent ID")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    message: str = Field(..., min_length=1, description="User message")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Conversation history")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    user_id: Optional[str] = Field(None, description="User identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")
    config: Optional[AgentConfig] = Field(None, description="Agent configuration")
    capabilities_required: List[AgentCapability] = Field(default_factory=list, description="Required capabilities")
    enable_streaming: bool = Field(False, description="Enable streaming response")
    timeout_seconds: Optional[int] = Field(None, ge=1, description="Request timeout in seconds")
    
    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v.strip()
    
    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("Timeout must be at least 1 second")
        return v


class AgentResponse(BaseModel):
    """Agent execution response."""
    request_id: str = Field(..., description="Original request identifier")
    agent_id: str = Field(..., description="Agent identifier")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode used")
    response: str = Field(..., description="Agent response")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Response metadata")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Response confidence")
    processing_time: float = Field(..., ge=0.0, description="Processing time in seconds")
    token_usage: Optional[Dict[str, int]] = Field(None, description="Token usage statistics")
    capabilities_used: List[AgentCapability] = Field(default_factory=list, description="Capabilities used")
    error: Optional[AgentError] = Field(None, description="Error information if failed")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    
    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class AgentInfo(BaseModel):
    """Agent information."""
    agent_id: str = Field(..., description="Agent identifier")
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode")
    status: AgentStatus = Field(..., description="Current status")
    capabilities: List[AgentCapability] = Field(default_factory=list, description="Available capabilities")
    config: AgentConfig = Field(..., description="Agent configuration")
    metrics: AgentMetrics = Field(..., description="Performance metrics")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")
    version: str = Field("1.0.0", description="Agent version")
    
    @property
    def is_healthy(self) -> bool:
        """Check if agent is healthy."""
        return self.status in [AgentStatus.IDLE, AgentStatus.PROCESSING, AgentStatus.STREAMING]
    
    @property
    def is_available(self) -> bool:
        """Check if agent is available for requests."""
        return self.status in [AgentStatus.IDLE] and self.is_healthy


class AgentStreamResponse(BaseModel):
    """Agent streaming response wrapper."""
    request_id: str = Field(..., description="Original request identifier")
    agent_id: str = Field(..., description="Agent identifier")
    execution_mode: AgentExecutionMode = Field(..., description="Execution mode used")
    chunk: StreamChunk = Field(..., description="Stream chunk")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Stream metadata")
    is_complete: bool = Field(False, description="Whether streaming is complete")
    final_response: Optional[str] = Field(None, description="Final complete response")
    error: Optional[AgentError] = Field(None, description="Error if streaming failed")