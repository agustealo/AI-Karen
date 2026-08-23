from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REQUIRES_APPROVAL = "requires_approval"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class AutomationTriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    EVENT = "event"
    CONDITIONAL = "conditional"


class AutomationTrigger(BaseModel):
    type: AutomationTriggerType
    schedule: Optional[str] = None
    event_name: Optional[str] = None
    condition: Optional[str] = None
    timezone: str = "UTC"
    next_run_at: Optional[datetime] = None


class AutomationExecutionConfig(BaseModel):
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: int = 120
    max_retries: int = 2
    retry_delay_seconds: int = 30


class AutomationMemoryPolicy(BaseModel):
    can_read: bool = True
    can_write: bool = True
    write_mode: Literal["full", "summary_only", "none"] = "summary_only"
    store_raw_tool_outputs: bool = False
    tenant_scope: str = "current_user"


class AutomationApprovalPolicy(BaseModel):
    required_to_create: bool = False
    required_before_execution: bool = False
    required_for_actions: List[str] = Field(default_factory=list)


class AutomationNotificationPolicy(BaseModel):
    channels: List[str] = Field(default_factory=list)
    only_on_failure: bool = False


class AutomationDraft(BaseModel):
    draft_id: str
    name: str
    goal: str
    trigger: AutomationTrigger
    execution: AutomationExecutionConfig
    memory: AutomationMemoryPolicy
    approval: AutomationApprovalPolicy
    notification: AutomationNotificationPolicy
    risk_level: Literal["low", "medium", "high"] = "low"
    confirmation_required: bool = True
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    status: str = "draft"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentAutomation(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: Literal["active", "paused", "disabled", "failed", "completed", "pending_approval"] = "active"
    trigger: AutomationTrigger
    execution: AutomationExecutionConfig
    memory: AutomationMemoryPolicy
    approval: AutomationApprovalPolicy
    notification: AutomationNotificationPolicy
    risk_level: str = "low"
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_from_message_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    tenant_id: Optional[str] = None


class AgentRun(BaseModel):
    id: str
    automation_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    correlation_id: str
    status: ExecutionStatus
    trigger_source: Literal["chat", "schedule", "manual", "webhook", "system"]
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    tools_used: List[Dict[str, Any]] = Field(default_factory=list)
    memory_recall_count: int = 0
    memory_persistence_status: str = "none"
    started_at: datetime
    completed_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FlowType(str, Enum):
    DECIDE_ACTION = "decide_action"
    CONVERSATION_PROCESSING = "conversation_processing"
    CONVERSATION_SUMMARY = "conversation_summary"
    GENERATE_FINAL_RESPONSE = "generate_final_response"


class ToolType(str, Enum):
    GET_CURRENT_DATE = "getCurrentDate"
    GET_CURRENT_TIME = "getCurrentTime"
    GET_WEATHER = "getWeather"
    QUERY_BOOK_DATABASE = "queryBookDatabase"
    CHECK_GMAIL_UNREAD = "checkGmailUnread"
    COMPOSE_GMAIL = "composeGmail"
    NONE = "none"


class ToolInput(BaseModel):
    location: Optional[str] = Field(None, description="Location for weather or time queries")
    book_title: Optional[str] = Field(None, description="Book title for database queries")
    gmail_recipient: Optional[str] = Field(None, description="Email recipient address")
    gmail_subject: Optional[str] = Field(None, description="Email subject line")
    gmail_body: Optional[str] = Field(None, description="Email body content")


class MemoryContext(BaseModel):
    content: str = Field(description="Memory content")
    similarity_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Similarity score")
    tags: Optional[List[str]] = Field(None, description="Memory tags")
    timestamp: Optional[int] = Field(None, description="Unix timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class PluginInfo(BaseModel):
    name: str = Field(description="Plugin name")
    description: str = Field(description="Plugin description")
    category: str = Field(description="Plugin category")
    enabled: bool = Field(description="Whether the plugin is enabled")


class FlowInput(BaseModel):
    prompt: str = Field(description="User input prompt")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Recent conversation history")
    user_settings: Dict[str, Any] = Field(default_factory=dict, description="User settings and preferences")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context information")
    user_id: Optional[str] = Field(None, description="User identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")
    short_term_memory: Optional[str] = Field(None, description="Short-term memory as string")
    long_term_memory: Optional[str] = Field(None, description="Long-term memory as string")
    keywords: Optional[List[str]] = Field(None, description="Extracted keywords")
    knowledge_graph_insights: Optional[str] = Field(None, description="Knowledge graph insights")
    memory_depth: Optional[str] = Field(None, description="Memory depth preference")
    personality_tone: Optional[str] = Field(None, description="Personality tone preference")
    personality_verbosity: Optional[str] = Field(None, description="Verbosity preference")
    personal_facts: Optional[List[str]] = Field(None, description="Personal facts to remember")
    custom_persona_instructions: Optional[str] = Field(None, description="Custom persona instructions")
    context_from_memory: Optional[List[MemoryContext]] = Field(None, description="Relevant memories from backend")
    available_plugins: Optional[List[PluginInfo]] = Field(None, description="Available plugins")


class FlowOutput(BaseModel):
    response: str = Field(description="Main response to the user")
    requires_plugin: bool = Field(False, description="Whether plugin execution is required")
    plugin_to_execute: Optional[str] = Field(None, description="Plugin name to execute")
    plugin_parameters: Optional[Dict[str, Any]] = Field(None, description="Parameters for plugin execution")
    memory_to_store: Optional[Dict[str, Any]] = Field(None, description="Memory data to store")
    suggested_actions: Optional[List[str]] = Field(None, description="Suggested actions for the user")
    ai_data: Optional[Dict[str, Any]] = Field(None, description="AI metadata for the response")
    proactive_suggestion: Optional[str] = Field(None, description="Proactive suggestion")
    tool_to_call: Optional[ToolType] = Field(None, description="Tool to call")
    tool_input: Optional[ToolInput] = Field(None, description="Input for tool execution")
    intermediate_response: Optional[str] = Field(None, description="Intermediate response before tool execution")
    suggested_new_facts: Optional[List[str]] = Field(None, description="New facts to remember")
    summary_was_generated: Optional[bool] = Field(None, description="Whether summary was generated")


class DecideActionInput(BaseModel):
    prompt: str = Field(description="User input prompt")
    short_term_memory: Optional[str] = Field(None, description="Short-term memory")
    long_term_memory: Optional[str] = Field(None, description="Long-term memory")
    keywords: Optional[List[str]] = Field(None, description="Extracted keywords")
    knowledge_graph_insights: Optional[str] = Field(None, description="Knowledge graph insights")
    memory_depth: Optional[str] = Field(None, description="Memory depth preference")
    personality_tone: Optional[str] = Field(None, description="Personality tone preference")
    personality_verbosity: Optional[str] = Field(None, description="Verbosity preference")
    personal_facts: Optional[List[str]] = Field(None, description="Personal facts")
    custom_persona_instructions: Optional[str] = Field(None, description="Custom persona instructions")


class DecideActionOutput(BaseModel):
    intermediate_response: str = Field(description="Initial response or acknowledgement")
    tool_to_call: ToolType = Field(ToolType.NONE, description="Tool to call")
    tool_input: Optional[ToolInput] = Field(None, description="Tool input parameters")
    suggested_new_facts: Optional[List[str]] = Field(None, description="Suggested new facts")
    proactive_suggestion: Optional[str] = Field(None, description="Proactive suggestion")
