import re
import html
import logging
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
from .contracts.errors import AgentError, AgentErrorCode

logger = logging.getLogger(__name__)

class SafetyLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class SafetyResult:
    is_safe: bool
    reason: Optional[str] = None
    flags: List[str] = field(default_factory=list)
    sanitized_content: Optional[str] = None

class MedusaSafetyManager:
    """Safety and security manager for AgentMedusa."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.malicious_patterns = self._load_malicious_patterns()
        self.sensitive_data_patterns = self._load_sensitive_data_patterns()
        self.validation_rules = {
            "agent_id_pattern": r"^[a-zA-Z0-9_-]{3,50}$",
            "forbidden_names": ["system", "admin", "root"],
            "max_message_size": 1024 * 1024, # 1MB
        }

    def _load_malicious_patterns(self) -> List[re.Pattern]:
        return [
            re.compile(r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC|ALTER)\b)", re.IGNORECASE),
            re.compile(r"(''|\';|';|\"|\";|\"|--|#|\/\*|\*\/|0x)", re.IGNORECASE),
            re.compile(r"(<script|javascript:|on\w+\s*=|eval\(|expression\()", re.IGNORECASE),
            re.compile(r"(;|\||&|\$\(|`|>|<|\${)", re.IGNORECASE),
            re.compile(r"(\.\./|\.\.\\)", re.IGNORECASE),
        ]

    def _load_sensitive_data_patterns(self) -> List[re.Pattern]:
        return [
            re.compile(r"\b(?:\d[ -]*?){13,16}\b"), # Credit Card
            re.compile(r"\b\d{3}[ -]?\d{2}[ -]?\d{4}\b"), # SSN
            re.compile(r"\b[A-Za-z0-9]{32,}\b"), # API Keys (approx)
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), # Email
        ]

    async def validate_input(self, text: str) -> SafetyResult:
        """Validate input for malicious patterns and size."""
        if len(text.encode("utf-8")) > self.validation_rules["max_message_size"]:
            return SafetyResult(is_safe=False, reason="Message too large", flags=["size_limit"])

        for pattern in self.malicious_patterns:
            if pattern.search(text):
                return SafetyResult(is_safe=False, reason="Malicious pattern detected", flags=["malicious_input"])
        return SafetyResult(is_safe=True)

    async def validate_agent_id(self, agent_id: str) -> Tuple[bool, Optional[str]]:
        """Validate an agent identifier."""
        if not re.match(self.validation_rules["agent_id_pattern"], agent_id):
            return False, "Invalid agent ID format"
        if agent_id.lower() in self.validation_rules["forbidden_names"]:
            return False, f"Agent ID '{agent_id}' is forbidden"
        return True, None

    def sanitize_content(self, text: str) -> str:
        """Sanitize content by redacting sensitive information and escaping HTML."""
        if not isinstance(text, str):
            return text

        sanitized = text
        for pattern in self.sensitive_data_patterns:
            sanitized = pattern.sub("[REDACTED]", sanitized)

        return html.escape(sanitized, quote=True)

    async def check_access(self, user_context: Dict[str, Any], agent_id: str, action: str) -> bool:
        """Check if a user has access to an agent for a specific action.

        NOTE: Authorization is owned by RuntimePolicy, not MedusaSafetyManager.
        This method exists only for local input validation hooks. It must NOT
        be used as the authoritative allow/deny decision.
        """
        if not agent_id or not isinstance(agent_id, str):
            return False
        if not re.match(self.validation_rules["agent_id_pattern"], agent_id):
            return False
        if agent_id.lower() in self.validation_rules["forbidden_names"]:
            return False
        return True

_safety_manager: Optional[MedusaSafetyManager] = None

def get_safety_manager() -> MedusaSafetyManager:
    global _safety_manager
    if _safety_manager is None:
        _safety_manager = MedusaSafetyManager()
    return _safety_manager
