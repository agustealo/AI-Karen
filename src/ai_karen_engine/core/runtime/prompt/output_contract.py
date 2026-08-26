"""
Output Schema Contract for PromptRuntime.

Provider-neutral contract for structured output requirements.
This can be rendered as instructions now and used for native
structured output support later via ExpressionGateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OutputFormat(str, Enum):
    """Supported output formats."""
    TEXT = "text"
    JSON = "json"
    JSON_SCHEMA = "json_schema"
    TOOL_RESULT = "tool_result"


class OutputFailurePolicy(str, Enum):
    """How to handle output format failures."""
    FAIL_FAST = "fail_fast"  # Reject responses that don't match format
    FALLBACK_TEXT = "fallback_text"  # Accept text if schema validation fails
    BEST_EFFORT = "best_effort"  # Try to coerce to requested format


@dataclass
class OutputSchemaContract:
    """Provider-neutral contract for output requirements."""
    
    schema_id: str
    schema_version: str
    format: OutputFormat = OutputFormat.TEXT
    json_schema: Optional[Dict[str, Any]] = None
    strict: bool = True
    allow_additional_properties: bool = False
    failure_policy: OutputFailurePolicy = OutputFailurePolicy.FAIL_FAST
    
    # Text rendering for instruction fallback
    instruction_template: str = ""
    
    # Validation rules
    required_fields: List[str] = field(default_factory=list)
    field_constraints: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_instruction(self) -> str:
        """Render this contract as natural language instructions."""
        if self.instruction_template:
            return self.instruction_template
        
        if self.format == OutputFormat.TEXT:
            return "Provide a clear, concise text response."
        
        if self.format == OutputFormat.JSON:
            return "Respond with valid JSON."
        
        if self.format == OutputFormat.JSON_SCHEMA and self.json_schema:
            return f"Respond with valid JSON matching this schema: {self.json_schema}"
        
        if self.format == OutputFormat.TOOL_RESULT:
            return "Provide the tool result in the expected format."
        
        return "Provide a response following the specified format."
    
    def validate_response(self, response: Any) -> tuple[bool, Optional[str]]:
        """Validate that a response meets the contract requirements."""
        if self.format == OutputFormat.TEXT:
            return True, None
        
        if self.format == OutputFormat.JSON:
            if isinstance(response, str):
                try:
                    import json
                    json.loads(response)
                    return True, None
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON: {e}"
            elif isinstance(response, dict):
                return True, None
        
        if self.format == OutputFormat.JSON_SCHEMA and self.json_schema:
            # Basic JSON validation (full schema validation would require jsonschema library)
            if isinstance(response, str):
                try:
                    import json
                    parsed = json.loads(response)
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON: {e}"
            else:
                parsed = response
            
            # Check required fields
            missing_fields = [f for f in self.required_fields if f not in parsed]
            if missing_fields:
                return False, f"Missing required fields: {missing_fields}"
            
            return True, None
        
        return True, None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert contract to dictionary for serialization."""
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "format": self.format.value,
            "json_schema": self.json_schema,
            "strict": self.strict,
            "allow_additional_properties": self.allow_additional_properties,
            "failure_policy": self.failure_policy.value,
            "required_fields": self.required_fields,
            "field_constraints": self.field_constraints,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputSchemaContract":
        """Create contract from dictionary."""
        return cls(
            schema_id=data["schema_id"],
            schema_version=data["schema_version"],
            format=OutputFormat(data.get("format", "text")),
            json_schema=data.get("json_schema"),
            strict=data.get("strict", True),
            allow_additional_properties=data.get("allow_additional_properties", False),
            failure_policy=OutputFailurePolicy(data.get("failure_policy", "fail_fast")),
            required_fields=data.get("required_fields", []),
            field_constraints=data.get("field_constraints", {}),
        )