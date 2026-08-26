"""
Observability event schemas and contracts.

Defines canonical event schemas for the entire AI-Karen observability system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.observability.contracts import RuntimeEventType, RuntimeEvent

logger = logging.getLogger("kari.observability.schemas")


class EventCategory(str, Enum):
    """Event categories for organization."""
    
    REQUEST = "request"
    INTELLIGENCE = "intelligence"
    CORTEX = "cortex"
    POLICY = "policy"
    MEMORY = "memory"
    PROMPT = "prompt"
    PROVIDER = "provider"
    RUNTIME = "runtime"
    PLUGIN = "plugin"
    WORKFLOW = "workflow"
    TOOL = "tool"
    PERSISTENCE = "persistence"
    LEARNING = "learning"
    SECURITY = "security"
    PERFORMANCE = "performance"
    OBSERVABILITY = "observability"


@dataclass
class EventSchema:
    """Schema definition for an event type."""
    
    event_type: RuntimeEventType
    category: EventCategory
    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    field_types: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    def validate_event(self, event: RuntimeEvent) -> List[str]:
        """Validate an event against this schema."""
        errors = []
        
        # Check required fields
        for field_name in self.required_fields:
            if not hasattr(event, field_name) or getattr(event, field_name) is None:
                errors.append(f"Required field '{field_name}' is missing or None")
        
        # Check field types
        for field_name, expected_type in self.field_types.items():
            if hasattr(event, field_name) and getattr(event, field_name) is not None:
                value = getattr(event, field_name)
                actual_type = type(value).__name__
                
                if expected_type == "string" and not isinstance(value, str):
                    errors.append(f"Field '{field_name}' must be string, got {actual_type}")
                elif expected_type == "integer" and not isinstance(value, int):
                    errors.append(f"Field '{field_name}' must be integer, got {actual_type}")
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    errors.append(f"Field '{field_name}' must be number, got {actual_type}")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"Field '{field_name}' must be boolean, got {actual_type}")
                elif expected_type == "array" and not isinstance(value, list):
                    errors.append(f"Field '{field_name}' must be array, got {actual_type}")
                elif expected_type == "object" and not isinstance(value, dict):
                    errors.append(f"Field '{field_name}' must be object, got {actual_type}")
        
        return errors


# Event schemas for all canonical event types
EVENT_SCHEMAS: Dict[RuntimeEventType, EventSchema] = {}


def _register_schemas():
    """Register all event schemas."""
    
    # Request lifecycle events
    EVENT_SCHEMAS[RuntimeEventType.REQUEST_RECEIVED] = EventSchema(
        event_type=RuntimeEventType.REQUEST_RECEIVED,
        category=EventCategory.REQUEST,
        required_fields=["event_id", "event_type", "timestamp"],
        optional_fields=["request_id", "correlation_id", "user_id", "tenant_id", "session_id", "conversation_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
        },
        description="Initial request received by the system",
        examples=[{
            "event_id": "req_123",
            "event_type": "request.received",
            "timestamp": "2024-01-01T12:00:00Z",
            "request_id": "req_123",
            "correlation_id": "corr_456",
            "user_id": "user_789",
            "tenant_id": "tenant_001",
        }],
        tags=["request", "ingress"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.REQUEST_STARTED] = EventSchema(
        event_type=RuntimeEventType.REQUEST_STARTED,
        category=EventCategory.REQUEST,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
        },
        description="Request processing started",
        tags=["request", "processing"],
    )
    
    # Intelligence layer events
    EVENT_SCHEMAS[RuntimeEventType.INTELLIGENCE_STARTED] = EventSchema(
        event_type=RuntimeEventType.INTELLIGENCE_STARTED,
        category=EventCategory.INTELLIGENCE,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
        },
        description="Intelligence processing started",
        tags=["intelligence", "processing"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.INTELLIGENCE_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.INTELLIGENCE_COMPLETED,
        category=EventCategory.INTELLIGENCE,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "status"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "status": "string",
        },
        description="Intelligence processing completed",
        tags=["intelligence", "processing"],
    )
    
    # CORTEX events
    EVENT_SCHEMAS[RuntimeEventType.CORTEX_DECISION] = EventSchema(
        event_type=RuntimeEventType.CORTEX_DECISION,
        category=EventCategory.CORTEX,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "intent"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "intent": "string",
        },
        description="CORTEX decision made",
        tags=["cortex", "decision"],
    )
    
    # Policy events
    EVENT_SCHEMAS[RuntimeEventType.POLICY_EVALUATED] = EventSchema(
        event_type=RuntimeEventType.POLICY_EVALUATED,
        category=EventCategory.POLICY,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "policy_decision_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "policy_decision_id": "string",
        },
        description="Policy evaluation completed",
        tags=["policy", "evaluation"],
    )
    
    # Memory events
    EVENT_SCHEMAS[RuntimeEventType.MEMORY_RECALL_STARTED] = EventSchema(
        event_type=RuntimeEventType.MEMORY_RECALL_STARTED,
        category=EventCategory.MEMORY,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
        },
        description="Memory recall started",
        tags=["memory", "recall"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.MEMORY_RECALL_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.MEMORY_RECALL_COMPLETED,
        category=EventCategory.MEMORY,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "memory_recall_count"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "memory_recall_count": "integer",
        },
        description="Memory recall completed",
        tags=["memory", "recall"],
    )
    
    # PromptRuntime events
    EVENT_SCHEMAS[RuntimeEventType.PROMPT_ASSEMBLY_STARTED] = EventSchema(
        event_type=RuntimeEventType.PROMPT_ASSEMBLY_STARTED,
        category=EventCategory.PROMPT,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "prompt_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "prompt_id": "string",
        },
        description="Prompt assembly started",
        tags=["prompt", "assembly"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.PROMPT_ASSEMBLY_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.PROMPT_ASSEMBLY_COMPLETED,
        category=EventCategory.PROMPT,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "prompt_id", "prompt_version"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "prompt_id": "string",
            "prompt_version": "string",
        },
        description="Prompt assembly completed",
        tags=["prompt", "assembly"],
    )
    
    # Provider events
    EVENT_SCHEMAS[RuntimeEventType.PROVIDER_ATTEMPT_STARTED] = EventSchema(
        event_type=RuntimeEventType.PROVIDER_ATTEMPT_STARTED,
        category=EventCategory.PROVIDER,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "provider", "model"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "provider": "string",
            "model": "string",
        },
        description="Provider attempt started",
        tags=["provider", "attempt"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.PROVIDER_ATTEMPT_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.PROVIDER_ATTEMPT_COMPLETED,
        category=EventCategory.PROVIDER,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "provider", "model", "status"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "provider": "string",
            "model": "string",
            "status": "string",
        },
        description="Provider attempt completed",
        tags=["provider", "attempt"],
    )
    
    # Plugin events
    EVENT_SCHEMAS[RuntimeEventType.PLUGIN_EXECUTION_STARTED] = EventSchema(
        event_type=RuntimeEventType.PLUGIN_EXECUTION_STARTED,
        category=EventCategory.PLUGIN,
        required_fields=["event_id", "event_type", "timestamp", "request_id"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "plugin_id", "plugin_version"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "plugin_id": "string",
            "plugin_version": "string",
        },
        description="Plugin execution started",
        tags=["plugin", "execution"],
    )
    
    EVENT_SCHEMAS[RuntimeEventType.PLUGIN_EXECUTION_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.PLUGIN_EXECUTION_COMPLETED,
        category=EventCategory.PLUGIN,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "plugin_id", "plugin_version", "status"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "plugin_id": "string",
            "plugin_version": "string",
            "status": "string",
        },
        description="Plugin execution completed",
        tags=["plugin", "execution"],
    )
    
    # Persistence events
    EVENT_SCHEMAS[RuntimeEventType.PERSISTENCE_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.PERSISTENCE_COMPLETED,
        category=EventCategory.PERSISTENCE,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
        },
        description="Persistence operation completed",
        tags=["persistence", "storage"],
    )
    
    # Request completion events
    EVENT_SCHEMAS[RuntimeEventType.REQUEST_COMPLETED] = EventSchema(
        event_type=RuntimeEventType.REQUEST_COMPLETED,
        category=EventCategory.REQUEST,
        required_fields=["event_id", "event_type", "timestamp", "request_id", "duration_ms"],
        optional_fields=["correlation_id", "user_id", "tenant_id", "session_id", "conversation_id", "status"],
        field_types={
            "event_id": "string",
            "event_type": "string",
            "timestamp": "string",
            "request_id": "string",
            "duration_ms": "number",
            "correlation_id": "string",
            "user_id": "string",
            "tenant_id": "string",
            "session_id": "string",
            "conversation_id": "string",
            "status": "string",
        },
        description="Request processing completed",
        tags=["request", "completion"],
    )


# Initialize schemas
_register_schemas()


class ObservabilityValidator:
    """Validates observability events against schemas."""
    
    def __init__(self):
        self.schemas = EVENT_SCHEMAS
    
    def validate_event(self, event: RuntimeEvent) -> List[str]:
        """Validate an event against its schema."""
        
        schema = self.schemas.get(event.event_type)
        if not schema:
            return [f"No schema found for event type: {event.event_type}"]
        
        return schema.validate_event(event)
    
    def validate_all_events(self, events: List[RuntimeEvent]) -> Dict[str, List[str]]:
        """Validate multiple events."""
        
        results = {}
        for event in events:
            errors = self.validate_event(event)
            if errors:
                results[event.event_id] = errors
        
        return results
    
    def get_schema(self, event_type: RuntimeEventType) -> Optional[EventSchema]:
        """Get schema for an event type."""
        return self.schemas.get(event_type)
    
    def list_schemas(self) -> List[RuntimeEventType]:
        """List all registered event types."""
        return list(self.schemas.keys())
    
    def get_schemas_by_category(self, category: EventCategory) -> List[EventSchema]:
        """Get schemas by category."""
        return [schema for schema in self.schemas.values() if schema.category == category]


# Global validator instance
_observability_validator: Optional[ObservabilityValidator] = None


def get_observability_validator() -> ObservabilityValidator:
    """Get or create the global observability validator."""
    global _observability_validator
    if _observability_validator is None:
        _observability_validator = ObservabilityValidator()
    return _observability_validator


def validate_event(event: RuntimeEvent) -> List[str]:
    """Validate a single event."""
    validator = get_observability_validator()
    return validator.validate_event(event)


def validate_events(events: List[RuntimeEvent]) -> Dict[str, List[str]]:
    """Validate multiple events."""
    validator = get_observability_validator()
    return validator.validate_all_events(events)