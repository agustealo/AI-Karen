"""
Agent UI Service Data Models

.. deprecated::
    Legacy UI models are deprecated. UI-facing contracts should migrate to
    ``ai_karen_engine.copilotkit.models`` or a dedicated API layer.
"""

from typing import Any, Dict, List, Optional, Union, Literal
from enum import Enum
from datetime import datetime
import warnings

try:
    from pydantic import BaseModel, Field, ConfigDict
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field, ConfigDict

warnings.warn(
    "ai_karen_engine.agents.agent_ui_models is deprecated.",
    DeprecationWarning,
    stacklevel=2,
)

# Import existing schemas
from .internal.agent_schemas import AgentTask, AgentResponse, TaskStatus


class ExecutionMode(str, Enum):
    """Execution mode enumeration for agent tasks."""
    NATIVE = "native"
    DEEP_AGENTS = "deep_agents"
    LANG_GRAPH = "lang_graph"
    AUTO = "auto"


class UIComponentType(str, Enum):
    """UI component type enumeration."""
    BUTTON = "button"
    MENU = "menu"
    SLIDER = "slider"
    INPUT = "input"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    PROGRESS = "progress"
    ALERT = "alert"
    CARD = "card"
    TABLE = "table"
    CHART = "chart"


class ContentType(str, Enum):
    """Content type enumeration for responses."""
    TEXT = "text"
    MARKDOWN = "markdown"
    CODE = "code"
    JSON = "json"
    HTML = "html"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"


class LayoutType(str, Enum):
    """Layout type enumeration for responses."""
    DEFAULT = "default"
    MENU = "menu"
    MOVIE_LIST = "movie_list"
    BULLET_LIST = "bullet_list"
    SYSTEM_STATUS = "system_status"
    CARD_GRID = "card_grid"
    TABLE_VIEW = "table_view"
    CHART_VIEW = "chart_view"


class OutputProfile(str, Enum):
    """Output profile enumeration."""
    PLAIN = "plain"
    PRETTY = "pretty"
    DEV_DOC = "dev_doc"


class InteractiveElement(BaseModel):
    """Interactive element schema for UI responses."""
    type: UIComponentType = Field(..., description="Type of the interactive element")
    id: str = Field(..., description="Unique identifier for the element")
    label: str = Field(..., description="Label for the element")
    action: str = Field(..., description="Action to perform when element is interacted with")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters for the action")
    enabled: bool = Field(True, description="Whether the element is enabled")
    visible: bool = Field(True, description="Whether the element is visible")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class ResponseMetadata(BaseModel):
    """Response metadata schema."""
    response_id: str = Field(..., description="Unique identifier for the response")
    content_type: ContentType = Field(..., description="Type of the content")
    layout_type: LayoutType = Field(LayoutType.DEFAULT, description="Layout type for the response")
    output_profile: OutputProfile = Field(OutputProfile.PRETTY, description="Output profile for the response")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the response")
    execution_time: float = Field(0.0, description="Execution time in seconds")
    agent_id: Optional[str] = Field(None, description="ID of the agent that generated the response")
    task_id: Optional[str] = Field(None, description="ID of the task this response is for")
    session_id: Optional[str] = Field(None, description="ID of the session")
    thread_id: Optional[str] = Field(None, description="ID of the conversation thread")
    is_streaming: bool = Field(False, description="Whether the response is streamed")
    is_partial: bool = Field(False, description="Whether this is a partial response")
    has_error: bool = Field(False, description="Whether the response contains an error")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class SendMessageRequest(BaseModel):
    """Send message request schema."""
    session_id: str = Field(..., description="ID of the session")
    thread_id: Optional[str] = Field(None, description="ID of the conversation thread")
    message: str = Field(..., description="Message content")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    execution_mode: ExecutionMode = Field(ExecutionMode.AUTO, description="Execution mode")
    agent_id: Optional[str] = Field(None, description="ID of the target agent")
    priority: int = Field(0, description="Priority of the message")
    timeout_seconds: Optional[int] = Field(None, description="Timeout in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class SendMessageResponse(BaseModel):
    """Send message response schema."""
    success: bool = Field(..., description="Whether the message was sent successfully")
    message_id: str = Field(..., description="ID of the message")
    task_id: Optional[str] = Field(None, description="ID of the created task")
    response: Optional[str] = Field(None, description="Immediate response if available")
    is_streaming: bool = Field(False, description="Whether the response will be streamed")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[str] = Field(None, description="Error message if any")
    
    model_config = ConfigDict(extra="allow")


class CreateDeepTaskRequest(BaseModel):
    """Create deep task request schema."""
    session_id: str = Field(..., description="ID of the session")
    thread_id: Optional[str] = Field(None, description="ID of the conversation thread")
    task_type: str = Field(..., description="Type of the task")
    description: Optional[str] = Field(None, description="Description of the task")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Input data for the task")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    agent_id: Optional[str] = Field(None, description="ID of the target agent")
    priority: int = Field(0, description="Priority of the task")
    timeout_seconds: Optional[int] = Field(None, description="Timeout in seconds")
    expected_output: Optional[Dict[str, Any]] = Field(None, description="Expected output format")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class CreateDeepTaskResponse(BaseModel):
    """Create deep task response schema."""
    success: bool = Field(..., description="Whether the task was created successfully")
    task_id: str = Field(..., description="ID of the created task")
    status: TaskStatus = Field(..., description="Status of the task")
    message: Optional[str] = Field(None, description="Response message")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[str] = Field(None, description="Error message if any")
    
    model_config = ConfigDict(extra="allow")


class GetTaskProgressRequest(BaseModel):
    """Get task progress request schema."""
    session_id: str = Field(..., description="ID of the session")
    task_id: str = Field(..., description="ID of the task")
    include_details: bool = Field(False, description="Whether to include detailed progress information")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class TaskProgress(BaseModel):
    """Task progress schema."""
    task_id: str = Field(..., description="ID of the task")
    status: TaskStatus = Field(..., description="Status of the task")
    progress: float = Field(0.0, description="Progress of the task (0.0 to 1.0)")
    message: Optional[str] = Field(None, description="Progress message")
    steps_completed: int = Field(0, description="Number of steps completed")
    total_steps: Optional[int] = Field(None, description="Total number of steps")
    current_step: Optional[str] = Field(None, description="Description of the current step")
    estimated_time_remaining: Optional[int] = Field(None, description="Estimated time remaining in seconds")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed progress information")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class GetTaskProgressResponse(BaseModel):
    """Get task progress response schema."""
    success: bool = Field(..., description="Whether the request was successful")
    task_progress: TaskProgress = Field(..., description="Task progress information")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[str] = Field(None, description="Error message if any")
    
    model_config = ConfigDict(extra="allow")


class CancelTaskRequest(BaseModel):
    """Cancel task request schema."""
    session_id: str = Field(..., description="ID of the session")
    task_id: str = Field(..., description="ID of the task to cancel")
    reason: Optional[str] = Field(None, description="Reason for cancellation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class CancelTaskResponse(BaseModel):
    """Cancel task response schema."""
    success: bool = Field(..., description="Whether the task was cancelled successfully")
    task_id: str = Field(..., description="ID of the task")
    status: TaskStatus = Field(..., description="Status of the task after cancellation")
    message: Optional[str] = Field(None, description="Response message")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[str] = Field(None, description="Error message if any")
    
    model_config = ConfigDict(extra="allow")


class AgentUIRequest(BaseModel):
    """Base agent UI request schema."""
    session_id: str = Field(..., description="ID of the session")
    thread_id: Optional[str] = Field(None, description="ID of the conversation thread")
    request_type: str = Field(..., description="Type of the request")
    data: Dict[str, Any] = Field(default_factory=dict, description="Request data")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class AgentUIResponse(BaseModel):
    """Base agent UI response schema."""
    success: bool = Field(..., description="Whether the request was successful")
    request_type: str = Field(..., description="Type of the request")
    data: Dict[str, Any] = Field(default_factory=dict, description="Response data")
    metadata: ResponseMetadata = Field(..., description="Response metadata")
    error: Optional[str] = Field(None, description="Error message if any")
    
    model_config = ConfigDict(extra="allow")


class AgentUIError(BaseModel):
    """Agent UI error schema."""
    error_code: str = Field(..., description="Error code")
    error_message: str = Field(..., description="Error message")
    error_details: Optional[str] = Field(None, description="Detailed error information")
    error_type: str = Field(..., description="Type of the error")
    severity: Literal["info", "warning", "error", "critical"] = Field(..., description="Severity of the error")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the error")
    request_id: Optional[str] = Field(None, description="ID of the request that caused the error")
    session_id: Optional[str] = Field(None, description="ID of the session")
    task_id: Optional[str] = Field(None, description="ID of the task if applicable")
    stack_trace: Optional[str] = Field(None, description="Stack trace if available")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(extra="allow")


class AgentUIServiceConfig(BaseModel):
    """Agent UI Service configuration schema."""
    service_name: str = Field("agent_ui_service", description="Name of the service")
    default_execution_mode: ExecutionMode = Field(ExecutionMode.AUTO, description="Default execution mode")
    default_timeout_seconds: int = Field(60, description="Default timeout in seconds")
    max_concurrent_tasks: int = Field(10, description="Maximum number of concurrent tasks")
    enable_streaming: bool = Field(True, description="Whether to enable response streaming")
    enable_interactive_elements: bool = Field(True, description="Whether to enable interactive elements")
    default_output_profile: OutputProfile = Field(OutputProfile.PRETTY, description="Default output profile")
    default_layout_type: LayoutType = Field(LayoutType.DEFAULT, description="Default layout type")
    enable_error_handling: bool = Field(True, description="Whether to enable error handling")
    enable_logging: bool = Field(True, description="Whether to enable logging")
    log_level: str = Field("INFO", description="Log level")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional configuration")
    
    model_config = ConfigDict(extra="allow")


class AgentUIServiceStatus(BaseModel):
    """Agent UI Service status schema."""
    service_name: str = Field(..., description="Name of the service")
    status: str = Field(..., description="Status of the service")
    is_healthy: bool = Field(..., description="Whether the service is healthy")
    uptime_seconds: float = Field(0.0, description="Uptime in seconds")
    active_sessions: int = Field(0, description="Number of active sessions")
    active_tasks: int = Field(0, description="Number of active tasks")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")
    version: str = Field("1.0.0", description="Version of the service")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional status information")
    
    model_config = ConfigDict(extra="allow")


class AgentUIServiceMetrics(BaseModel):
    """Agent UI Service metrics schema."""
    requests_received: int = Field(0, description="Number of requests received")
    requests_processed: int = Field(0, description="Number of requests processed")
    requests_failed: int = Field(0, description="Number of requests failed")
    average_response_time: float = Field(0.0, description="Average response time in seconds")
    tasks_created: int = Field(0, description="Number of tasks created")
    tasks_completed: int = Field(0, description="Number of tasks completed")
    tasks_failed: int = Field(0, description="Number of tasks failed")
    tasks_cancelled: int = Field(0, description="Number of tasks cancelled")
    sessions_created: int = Field(0, description="Number of sessions created")
    sessions_active: int = Field(0, description="Number of active sessions")
    messages_sent: int = Field(0, description="Number of messages sent")
    streaming_responses: int = Field(0, description="Number of streaming responses")
    interactive_elements_rendered: int = Field(0, description="Number of interactive elements rendered")
    errors_encountered: int = Field(0, description="Number of errors encountered")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metrics")
    
    model_config = ConfigDict(extra="allow")