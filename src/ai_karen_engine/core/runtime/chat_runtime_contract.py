from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ai_karen_engine.auth.models import UserData
    from ai_karen_engine.persistence.repositories.chat_run_repository import ChatRunLease

from ai_karen_engine.utils.chat_helpers import normalize_session_id


# Only execution-bearing fields belong here. Mutable telemetry such as
# degradation_state and audit_context is deliberately not an authorization.
_MODEL_GRANT_FIELDS = (
    "topology",
    "allowed_capabilities",
    "allowed_tools",
    "allowed_plugins",
    "allowed_agents",
    "provider_constraints",
    "resource_scope",
    "approval_requirements",
    "reasoning_modes",
    "memory_scope",
    "workflow_id",
    "agent_topology",
    "degraded_allowed",
)


def _model_grant_snapshot(plan: Any) -> Dict[str, Any]:
    """Copy the original plan's execution grants, never its mutable references."""
    return {
        name: deepcopy(getattr(plan, name))
        for name in _MODEL_GRANT_FIELDS
    }


class ChatExecutionMode(str, Enum):
    """Authoritative runtime mode for a single chat execution.

    The control plane owns system availability; the runtime reports the mode
    it resolved for this specific request.
    """

    NORMAL = "normal"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    EMERGENCY = "emergency"
    GRAPH = "graph"


class ChatExecutionStatus(str, Enum):
    """Terminal status of a chat execution attempt."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"
    GATE = "gate"


class ChatStreamEventType(str, Enum):
    """Canonical, transport-agnostic event types emitted by ChatRuntime.execute_stream.

    Every transport (SSE, WebSocket, CopilotKit, HTTP) serializes the same
    semantics via ``ChatStreamChunk.type`` using this enum so the frontend
    only needs one normalizer.
    """

    STATUS = "status"
    CONTENT = "content"
    AGENT_STEP = "agent_step"
    TOOL = "tool"
    CITATION = "citation"
    PRESENTATION = "presentation"
    APPROVAL = "approval"
    WARNING = "warning"
    ERROR = "error"
    COMPLETE = "complete"


class ToolType(str, Enum):
    """Tool type classifications for chat execution."""

    SYSTEM = "system"
    SEARCH = "search"
    CODE = "code"
    INTEGRATION = "integration"
    CUSTOM = "custom"


@dataclass
class ChatExecutionContext:
    """Stable request/tenant/session identity for one chat execution.

    This is the single identity carrier that must propagate from ingress
    through provider, memory, plugin, and persistence. When ingress has not
    assigned a conversation yet, the context derives one stable UUID from the
    tenant and session exactly once so every downstream owner observes the
    same durable identity. Tenant scope is never synthesized; missing tenant
    identity remains empty so authenticated/runtime guards can fail closed.
    """

    user_id: str
    tenant_id: str = ""
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    authenticated_user: Optional["UserData"] = field(default=None, repr=False, compare=False)


    def bind_runtime_model_authority(self, plan: Any, meter: Any) -> None:
        """Pin original RuntimePolicy objects on the authenticated request.

        Only ChatRuntime owns initial binding after constructing its plan and
        meter. Keeping this state outside dataclass fields prevents copied
        or serialized ChatExecutionContext values from inheriting authority.
        """
        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan, ExecutionBudgetMeter,
        )

        self.require_authenticated_user()
        if (
            not isinstance(plan, AuthorizedExecutionPlan)
            or not isinstance(meter, ExecutionBudgetMeter)
            or meter.budget is not plan.budget
            or not meter.retains_initial_budget_limits()
            or not self.request_id
            or not self.correlation_id
            or not plan.matches_execution_scope(
                user_id=self.user_id,
                tenant_id=self.tenant_id,
                session_id=self.session_id,
                policy_decision_id=plan.policy_decision_id,
            )
        ):
            raise PermissionError("runtime_model_execution_authority_invalid")
        key = (
            self.tenant_id,
            self.user_id,
            self.session_id or "",
            self.request_id,
            self.correlation_id,
            plan.policy_decision_id,
            plan.execution_id,
        )
        # A never-used ID is not a grant. Only the original RuntimePolicy
        # issuer-returned decision bound by RuntimeDecisionPipeline can allow
        # the first plan/meter registration. Cloned dataclasses lack that
        # nonserialized witness, regardless of changed execution ID.
        issuance = self.__dict__.get("_runtime_policy_issuance")
        if (
            not isinstance(issuance, tuple)
            or len(issuance) != 2
            or not issuance[0].verifies_chat_model_policy(
                context=self, plan=plan,
            )
        ):
            raise PermissionError("runtime_model_execution_authority_invalid")
        binding = self.__dict__.get("_runtime_model_authority")
        if binding is None:
            self.__dict__["_runtime_model_authority"] = (plan, meter)
            self.__dict__["_runtime_model_root_grants"] = (
                _model_grant_snapshot(plan)
            )
            self.__dict__["_runtime_model_child_plans"] = []
            self.__dict__["_runtime_model_authority_key"] = key
        elif (
            binding[0] is not plan
            or binding[1] is not meter
            or self.__dict__.get("_runtime_model_authority_key") != key
            or self.__dict__.get("_runtime_model_root_grants")
            != _model_grant_snapshot(plan)
        ):
            raise PermissionError("runtime_model_execution_authority_invalid")

    def original_runtime_model_plan(self, meter: Any) -> Any | None:
        """Expose the original policy plan only for its original meter."""
        binding = self.__dict__.get("_runtime_model_authority")
        if (
            binding is None
            or binding[1] is not meter
            or not meter.retains_initial_budget_limits()
        ):
            return None
        root = binding[0]
        if (
            self.__dict__.get("_runtime_model_root_grants")
            != _model_grant_snapshot(root)
        ):
            return None
        key = self.__dict__.get("_runtime_model_authority_key")
        if not isinstance(key, tuple):
            return None
        root = binding[0]
        issuance = self.__dict__.get("_runtime_policy_issuance")
        if (
            not isinstance(issuance, tuple)
            or len(issuance) != 2
            or not issuance[0].verifies_chat_model_policy(
                context=self, plan=root,
            )
        ):
            return None
        if key != (
            self.tenant_id,
            self.user_id,
            self.session_id or "",
            self.request_id,
            self.correlation_id,
            root.policy_decision_id,
            root.execution_id,
        ):
            return None
        return root

    def register_runtime_model_child_plan(self, plan: Any, meter: Any) -> None:
        """Register a Medusa-scoped derivative without minting a new grant."""
        from dataclasses import replace

        root = self.original_runtime_model_plan(meter)
        if root is None or type(plan) is not type(root):
            raise PermissionError("runtime_model_execution_authority_invalid")
        if plan is root:
            return
        if (
            plan.budget is not root.budget
            or replace(
                root,
                allowed_tools=list(plan.allowed_tools),
                allowed_plugins=list(plan.allowed_plugins),
                allowed_agents=list(plan.allowed_agents),
            ) != plan
        ):
            raise PermissionError("runtime_model_execution_authority_invalid")
        original = self.__dict__.get("_runtime_model_root_grants")
        if not isinstance(original, dict):
            raise PermissionError("runtime_model_execution_authority_invalid")
        for attribute in ("allowed_tools", "allowed_plugins", "allowed_agents"):
            # An empty immutable root allowlist is a denial, not a wildcard.
            policy_allowed = set(original[attribute])
            if not set(getattr(plan, attribute)).issubset(policy_allowed):
                raise PermissionError("runtime_model_execution_authority_invalid")
        children = self.__dict__["_runtime_model_child_plans"]
        if not any(child is plan for child, _ in children):
            children.append((plan, _model_grant_snapshot(plan)))

    def is_runtime_model_plan_authorized(self, plan: Any, meter: Any) -> bool:
        """Only root and approved child object identities may execute."""
        root = self.original_runtime_model_plan(meter)
        return (
            root is not None
            and (
                plan is root
                or any(
                    child is plan and approved == _model_grant_snapshot(plan)
                    for child, approved in self.__dict__.get(
                        "_runtime_model_child_plans", ()
                    )
                )
            )
        )


    def bind_runtime_attachment_scope(
        self, plan: Any, meter: Any, references: list[dict[str, str]],
    ) -> None:
        """Bind selected source revisions to the original, non-copyable grant."""
        from ai_karen_engine.services.database.repositories.conversation_repository import (
            validate_draft_attachment_references,
        )

        self.require_authenticated_user()
        selected = validate_draft_attachment_references(references)
        root = self.original_runtime_model_plan(meter)
        if (
            not selected or root is None or root is not plan
            or not self.is_runtime_model_plan_authorized(plan, meter)
            or "data:read" not in root.allowed_capabilities
        ):
            raise PermissionError("runtime_attachment_authority_invalid")
        scope = tuple((item["source_id"], item["revision"]) for item in selected)
        issued_scope = root.resource_scope.get("attachment_references", [])
        if (
            not isinstance(issued_scope, list)
            or tuple(
                (item.get("source_id"), item.get("revision"))
                for item in issued_scope if isinstance(item, dict)
            ) != scope
            or len(issued_scope) != len(scope)
        ):
            raise PermissionError("runtime_attachment_scope_denied")
        current = self.__dict__.get("_runtime_attachment_scope")
        if current is not None and (
            current[0] is not plan or current[1] is not meter or current[2] != scope
        ):
            raise PermissionError("runtime_attachment_authority_invalid")
        self.__dict__["_runtime_attachment_scope"] = (plan, meter, scope)

    def bind_runtime_attachment_documents(
        self, plan: Any, meter: Any, documents: list[dict[str, str]],
    ) -> None:
        """Publish verified document content atomically after every source passes."""
        self.require_authenticated_user()
        current = self.__dict__.get("_runtime_attachment_scope")
        if (
            current is None
            or current[0] is not plan or current[1] is not meter
            or not self.is_runtime_model_plan_authorized(plan, meter)
            or len(documents) != len(current[2])
            or any(
                not isinstance(item, dict)
                or item.get("source_id") != source_id
                or item.get("revision") != revision
                or not isinstance(item.get("text"), str)
                for item, (source_id, revision) in zip(documents, current[2])
            )
            or "_runtime_attachment_documents" in self.__dict__
        ):
            raise PermissionError("runtime_attachment_authority_invalid")
        self.__dict__["_runtime_attachment_documents"] = tuple(
            (item["source_id"], item["revision"], item["text"])
            for item in documents
        )

    def runtime_attachment_documents(self) -> list[dict[str, str]]:
        """Release content only while the original policy plan/meter remain valid."""
        self.require_authenticated_user()
        current = self.__dict__.get("_runtime_attachment_scope")
        documents = self.__dict__.get("_runtime_attachment_documents")
        if current is None:
            return []
        plan, meter, scope = current
        if (
            documents is None
            or not self.is_runtime_model_plan_authorized(plan, meter)
            or tuple((source_id, revision) for source_id, revision, _ in documents)
            != scope
        ):
            raise PermissionError("runtime_attachment_authority_invalid")
        return [
            {"source_id": source_id, "revision": revision, "text": text}
            for source_id, revision, text in documents
        ]

    def require_authenticated_user(self) -> "UserData":
        """Require the ingress principal and matching user and tenant scope."""
        from ai_karen_engine.auth.models import UserData

        principal = self.authenticated_user
        if not isinstance(principal, UserData):
            raise PermissionError("authenticated_principal_required")
        if not principal.is_active or not principal.is_verified:
            raise PermissionError("authenticated_principal_inactive")
        if str(principal.user_id) != str(self.user_id) or str(principal.tenant_id) != str(self.tenant_id):
            raise PermissionError("authenticated_principal_scope_mismatch")
        return principal

    def __post_init__(self) -> None:
        if self.conversation_id or not self.session_id:
            return
        tenant_id = str(self.tenant_id or "").strip()
        if not tenant_id:
            return
        normalized_session_id = normalize_session_id(self.session_id)
        identity = ":".join(
            (
                "ai-karen",
                "conversation",
                tenant_id,
                normalized_session_id,
            )
        )
        self.conversation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    def require_conversation_id(self) -> str:
        """Return the canonical conversation identity established by this context."""
        conversation_id = str(self.conversation_id or "").strip()
        if not conversation_id:
            raise ValueError("conversation_identity_incomplete:conversation_id")
        return conversation_id


@dataclass(frozen=True, slots=True)
class PersonaExecutionSnapshot:
    """Runtime-authenticated persona selection frozen for one execution.

    Persona IDs here are provenance and presentation references, never
    authorization to read resources or perform actions. Memory retrieval must
    still enforce its own tenant/user/purpose and source ACL checks.
    """

    user_id: str
    tenant_id: str
    status: str  # "ready", "none", "unavailable"
    persona_id: Optional[str] = None
    selection_revision: int = 0
    tone: str = ""
    verbosity: str = ""
    language_style: str = ""
    memory_filter_required: bool = False

    def matches(self, context: ChatExecutionContext) -> bool:
        return (
            self.user_id == str(context.user_id)
            and self.tenant_id == str(context.tenant_id)
        )


@dataclass
class ChatExecutionRequest:
    """Canonical input contract for the chat runtime.

    Every transport (HTTP, WebSocket, CopilotKit, future internal paths)
    normalizes its external shape into this object before delegating to
    ``ChatRuntime.execute``.
    """

    messages: List[Dict[str, Any]]
    context: ChatExecutionContext
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Untrusted selection, not permission or stored document content.
    attachment_references: List[Dict[str, str]] = field(default_factory=list)
    # Minted by runtime admission only; never copied from SDK metadata or prompt.
    runtime_run_lease: Optional["ChatRunLease"] = field(
        default=None, repr=False, compare=False,
    )
    # Assigned only by ChatRuntime after authenticating ingress identity.
    # init=False prevents SDK request construction from supplying this field.
    persona_snapshot: Optional[PersonaExecutionSnapshot] = field(
        default=None, init=False, repr=False, compare=False,
    )


@dataclass
class ChatRuntimeMetadata:
    """Single normalizer for the user-facing chat response metadata contract.

    One schema, one place. Required fields from the runtime authority audit.
    """

    correlation_id: str
    latency_ms: float = 0.0

    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_target: Optional[str] = None
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    # Scalar, bounded, Runtime-authorized learning lineage. Does not expose
    # raw personal memories, task prompts, model scores or checkpoint bytes.
    model_calls_observed: Optional[int] = None
    model_selection_source: Optional[str] = None
    learning_signal_status: Optional[str] = None
    learning_signal_version: Optional[str] = None
    learned_context_status: Optional[str] = None
    learned_memory_refs_included: Optional[int] = None
    actual_target: Optional[str] = None
    runtime_engine: Optional[str] = None
    protocol: Optional[str] = None
    locality: Optional[str] = None
    response_source: Optional[str] = None

    fallback_level: int = 0
    fallback_reason: Optional[str] = None
    degraded_mode: bool = False
    degradation_reason: Optional[str] = None

    mode: str = "normal"
    used_fallback: bool = False
    context_used: bool = False

    # Stable backend-confirmed identifiers surfaced to clients.
    response_id: Optional[str] = None
    conversation_id: Optional[str] = None
    assistant_message_id: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Render the canonical metadata plus any extension fields."""
        base: Dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "latency_ms": self.latency_ms,
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "requested_target": self.requested_target,
            "actual_provider": self.actual_provider,
            "actual_model": self.actual_model,
            "actual_target": self.actual_target,
            "runtime_engine": self.runtime_engine,
            "protocol": self.protocol,
            "locality": self.locality,
            "response_source": self.response_source,
            "fallback_level": self.fallback_level,
            "fallback_reason": self.fallback_reason,
            "degraded_mode": self.degraded_mode,
            "degradation_reason": self.degradation_reason,
            "mode": self.mode,
            "used_fallback": self.used_fallback,
            "context_used": self.context_used,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "assistant_message_id": self.assistant_message_id,
        }
        base.update(self.extra)
        # Backwards compatible: ordinary direct chat responses do not sprout
        # six additional null properties merely because Deep Agents learning
        # metadata exists as a typed extension.
        for key in (
            "model_calls_observed", "model_selection_source",
            "learning_signal_status", "learning_signal_version",
            "learned_context_status", "learned_memory_refs_included",
        ):
            value = getattr(self, key)
            if value is not None:
                base[key] = value
        return base


@dataclass
class ChatExecutionResult:
    """Canonical output contract for the chat runtime.

    When ``status`` is ``GATE`` the ``gate_response`` carries the control
    plane decision (maintenance / degraded / emergency) and the transport
    must serialize it instead of a normal answer.
    """

    answer: str
    metadata: ChatRuntimeMetadata
    structured_content: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    status: ChatExecutionStatus = ChatExecutionStatus.OK
    gate_response: Optional[Any] = None

    citations: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field


class ChatStreamChunk(BaseModel):
    """Granular output chunk for streaming responses."""

    model_config = ConfigDict(protected_namespaces=())

    type: ChatStreamEventType = Field(
        ..., description="Event type. Canonical values live in ChatStreamEventType."
    )
    content: str = Field("", description="The text fragment or status update")
    correlation_id: str = Field(..., description="Request tracking identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional chunk metadata")

    event_id: Optional[str] = Field(
        None, description="Unique identifier for this chunk/event"
    )
    sequence: Optional[int] = Field(
        None, description="Monotonically increasing chunk sequence number"
    )
    request_id: Optional[str] = Field(
        None, description="Identifies the originating request"
    )
    response_id: Optional[str] = Field(
        None, description="Identifies the runtime response"
    )
    conversation_id: Optional[str] = Field(
        None, description="Conversation context identifier"
    )
    timestamp: Optional[datetime] = Field(
        None, description="When this chunk was emitted"
    )

    def to_sse_payload(self) -> Dict[str, Any]:
        """Serialize to a transport-agnostic dict suitable for SSE data lines."""
        return {
            "type": self.type.value if isinstance(self.type, ChatStreamEventType) else self.type,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "request_id": self.request_id,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class CanonicalChatRequest(BaseModel):
    """Input payload for the canonical chat orchestration runtime."""
    model_config = ConfigDict(protected_namespaces=())

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable request identifier")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Cross-service correlation identifier")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier when available")
    message: str = Field(..., description="The user's message content")
    user_id: str = Field(..., description="Unique user identifier")
    org_id: Optional[str] = Field(None, description="Organization or Tenant ID")
    conversation_id: str = Field(..., description="Active conversation context ID")
    session_id: Optional[str] = Field(None, description="Optional session tracking ID")
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable user message identifier")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Associated file or media links")
    include_context: bool = Field(True, description="Whether to perform RAG recall")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional request-specific metadata")
    streaming: bool = Field(False, description="Whether to return a stream generator")
    stream: bool = Field(False, description="Alias for streaming")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Request creation timestamp")


class CanonicalChatResponse(BaseModel):
    """Terminal output from the canonical orchestration runtime."""
    model_config = ConfigDict(protected_namespaces=())

    request_id: Optional[str] = Field(None, description="Source request identifier")
    response: str = Field(..., description="The final generated response")
    correlation_id: str = Field(..., description="Request tracking identifier")
    conversation_id: Optional[str] = Field(None, description="Conversation identifier")
    assistant_message_id: Optional[str] = Field(None, description="Persisted assistant message identifier")
    processing_time: float = Field(..., description="Total execution time in seconds")
    status: ChatExecutionStatus = Field(..., description="Terminal processing state")
    used_fallback: bool = Field(False, description="Whether a fallback model was used")
    context_used: bool = Field(False, description="Whether RAG context was utilized")
    execution_path: Optional[str] = Field(None, description="Execution path selected by the orchestrator")
    structured_content: Dict[str, Any] = Field(default_factory=dict, description="Rich JSON output or application state")
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="Suggested or triggered automation actions")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Detailed execution and model metadata")
    telemetry: Dict[str, Any] = Field(default_factory=dict, description="Telemetry payload for frontend/runtime inspection")
    error: Optional[str] = Field(None, description="Error message if failed")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Response creation timestamp")
