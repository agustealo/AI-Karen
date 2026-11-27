from __future__ import annotations

"""Runtime-owned governed evidence resolution.

CORTEX states what evidence it needs. RuntimePolicy authorizes access. This
resolver performs the authorized retrieval exactly once and returns the same
typed ``CognitiveContext`` that CORTEX Stage 2 and ChatRuntime consume.

Semantic-memory retrieval is delegated exclusively to ``MemoryRuntimeManager``
which in turn delegates selection/ranking to NeuroRecall. Durable conversation
history is delegated exclusively to ``ConversationRuntimeGateway`` which adapts
the canonical ``ConversationRepository``. The two evidence domains remain
separate and neither is allowed to impersonate the other.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirement,
    EvidenceContradiction,
    EvidenceContradictionStatus,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
    EvidenceFactSemantics,
)
from ai_karen_engine.core.memory.semantic_contract import FactCardinality
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    get_conversation_runtime_gateway,
)
from src.ai_karen_engine.platform.observability import get_observability_emitter
from src.ai_karen_engine.platform.observability.contracts import EventType as RuntimeEventType

logger = get_logger(__name__)


class RuntimeEvidenceResolver:
    """Resolve RuntimePolicy-authorized evidence into one typed context truth."""

    MEMORY_RESOLVER_ID = "runtime.evidence.memory"
    CONVERSATION_RESOLVER_ID = "runtime.evidence.conversation"
    RESOLVER_ID = MEMORY_RESOLVER_ID
    RESOLVER_VERSION = "1"

    def __init__(
        self,
        *,
        memory_manager: Any | None = None,
        conversation_gateway: ConversationRuntimeGateway | None = None,
        proactive_continuity_service: Any | None = None,
        persona_service: Any | None = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._conversation_gateway = conversation_gateway
        self._proactive_continuity_service = proactive_continuity_service
        self._persona_service = persona_service
        self._emitter = get_observability_emitter()

    async def resolve(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
    ) -> CognitiveContext:
        """Resolve every currently authorized source exactly once.

        Unsupported authorized sources remain in ``unresolved_sources``. A source
        is removed from that list only after its resolver actually completed,
        including a successful empty result set.
        """
        authorized = set(cognitive_context.authorized_sources)
        for requirement in cognitive_context.requirements.requirements:
            if requirement.source.value not in authorized:
                continue
            if requirement.source is EvidenceSource.MEMORY:
                await self._resolve_memory(request, cognitive_context, requirement)
            elif requirement.source is EvidenceSource.USER_MODEL:
                await self._resolve_continuity(
                    request,
                    cognitive_context,
                    requirement,
                )
            elif requirement.source is EvidenceSource.CONVERSATION:
                await self._resolve_conversation(
                    request,
                    cognitive_context,
                    requirement,
                )
        return cognitive_context

    @staticmethod
    def authorized_semantic_value(
        cognitive_context: CognitiveContext | None,
        *,
        tenant_id: str,
        user_id: str,
        attribute: str,
    ) -> str | None:
        """Read one structured profile attribute from already-authorized evidence.

        This is not a second recall or a memory permission decision. The
        evidence came through RuntimePolicy and NeuroRecall; fail closed on
        scope mismatches, denied or unresolved sources, and contradictions.
        """
        from ai_karen_engine.core.runtime.evidence_sufficiency import (
            EvidenceSufficiencyStatus, evaluate_personal_evidence,
        )

        result = evaluate_personal_evidence(
            cognitive_context, tenant_id=tenant_id, user_id=user_id,
            attribute=attribute,
        )
        return result.value if result.status is EvidenceSufficiencyStatus.SUPPORTED else None

    @staticmethod
    def _memory_retrieval_query(
        request: ChatExecutionRequest, requirement: ContextRequirement
    ) -> str:
        """Preserve requested semantics across emphatic personal-recall phrasing.

        Normalize only the recall search query. The original utterance remains
        intact for CORTEX, audit, conversation and persistence. No additional
        memory source is authorized here.
        """
        governed_query = str(requirement.metadata.get("retrieval_query") or "").strip()
        if governed_query:
            return governed_query
        query = RuntimeEvidenceResolver._latest_user_message(request)
        from ai_karen_engine.core.intelligence.profile_attribute import (
            referenced_profile_attribute,
        )

        from ai_karen_engine.core.intelligence.profile_attribute import (
            is_profile_summary_expansion_followup,
            is_profile_summary_followup,
            is_profile_summary_request,
        )
        if is_profile_summary_request(query):
            return "who am i"
        if is_profile_summary_expansion_followup(query, request.messages):
            # A request for additional facts must not re-run the canonical
            # identity-key lookup ("who am i") that produced the previous
            # name/birthplace/residence answer. Keep user/tenant policy scope
            # intact and search for broader authorized personal knowledge.
            return "what else do you know about me"
        if is_profile_summary_followup(query, request.messages):
            return "who am i"

        # Query by the requested fact, not by a sanitized user utterance.
        # The semantic query is internal and the original words are untouched.
        attribute = referenced_profile_attribute(query, request.messages)
        canonical_queries = {
            "preferred_name": "what is my name",
            "origin_location": "where am i from",
            "upbringing_location": "where did i grow up",
            "birthplace": "where was i born",
            "residence_location": "where do i live",
            "work_location": "where do i work",
            "current_location": "where am i currently",
        }
        return canonical_queries.get(attribute, query)

    async def _resolve_memory(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
        requirement: ContextRequirement,
    ) -> None:
        ctx = request.context
        self._emitter.emit(
            RuntimeEventType.MEMORY_RECALL_STARTED,
            policy_decision_id=cognitive_context.policy_decision_id,
            metadata={
                "context_id": cognitive_context.context_id,
                "resolver_id": self.MEMORY_RESOLVER_ID,
            },
        )

        persona_filter: str | None = None
        snapshot = request.persona_snapshot
        if snapshot is not None:
            if not snapshot.matches(ctx) or snapshot.status == "unavailable":
                # Unavailable or mismatched persona state never widens recall.
                cognitive_context.metadata["memory_recall_status"] = "unavailable"
                cognitive_context.metadata["memory_degraded"] = True
                cognitive_context.metadata["memory_degradation_reason"] = (
                    "persona_snapshot_unavailable"
                )
                return
            if snapshot.memory_filter_required:
                if not snapshot.persona_id:
                    cognitive_context.metadata["memory_recall_status"] = "unavailable"
                    cognitive_context.metadata["memory_degraded"] = True
                    cognitive_context.metadata["memory_degradation_reason"] = (
                        "persona_snapshot_missing_id"
                    )
                    return
                persona_filter = snapshot.persona_id
        else:
            # Compatibility for standalone resolver callers. Normal ChatRuntime
            # freezes selection before CORTEX invokes this resolver.
            try:
                from ai_karen_engine.services.persona.persona_service import get_persona_service

                persona_service = self._persona_service or get_persona_service()
                preferences = await persona_service.get_user_preferences(
                    user_id=ctx.user_id, tenant_id=ctx.tenant_id
                )
                if (
                    preferences.enable_persona_memory_filtering
                    and not preferences.cross_persona_memory_sharing
                    and preferences.active_persona_id
                ):
                    persona_filter = preferences.active_persona_id
            except Exception as exc:
                cognitive_context.metadata["memory_recall_status"] = "unavailable"
                cognitive_context.metadata["memory_degraded"] = True
                cognitive_context.metadata["memory_degradation_reason"] = (
                    "persona_scope_unavailable"
                )
                logger.warning(
                    "memory.persona_scope_unavailable",
                    extra={
                        "correlation_id": ctx.correlation_id,
                        "error_type": type(exc).__name__,
                    },
                )
                return

        try:
            memory_manager = self._memory_manager or self._get_memory_manager()
            result = await memory_manager.recall_context(
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                query=self._memory_retrieval_query(request, requirement),
                top_k=max(0, int(requirement.max_items or 0)),
                tiers=tuple(requirement.classes),
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                correlation_id=ctx.correlation_id,
                request_id=ctx.request_id,
                persona_filter=persona_filter,
            )
        except Exception as exc:
            logger.warning(
                "Runtime evidence memory resolution failed",
                extra={
                    "correlation_id": ctx.correlation_id,
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "error_type": type(exc).__name__,
                },
            )
            cognitive_context.metadata.update(
                {
                    "memory_recall_status": "failed",
                    "memory_recall_count": 0,
                    "memory_latency_ms": 0.0,
                    "memory_degraded": True,
                    "memory_degradation_reason": "memory_retrieval_unavailable",
                    "memory_resolver_id": self.MEMORY_RESOLVER_ID,
                }
            )
            self._emitter.emit(
                RuntimeEventType.MEMORY_RECALL_COMPLETED,
                policy_decision_id=cognitive_context.policy_decision_id,
                memory_recall_count=0,
                metadata={
                    "context_id": cognitive_context.context_id,
                    "resolver_id": self.MEMORY_RESOLVER_ID,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return

        now = datetime.now(timezone.utc)
        raw_items = list(result.get("results") or [])
        max_items = max(0, int(requirement.max_items or 0))
        if max_items:
            raw_items = raw_items[:max_items]

        try:
            resolved = [
                self._memory_item_to_evidence(
                    item,
                    request=request,
                    retrieved_at=now,
                )
                for item in raw_items
            ]
        except (TypeError, ValueError, OverflowError) as exc:
            # A malformed canonical validity interval is not an unbounded
            # fact. Keep memory unresolved; never publish a partial batch.
            cognitive_context.metadata.update({
                "memory_recall_status": "failed",
                "memory_recall_count": 0,
                "memory_degraded": True,
                "memory_degradation_reason": "invalid_memory_evidence",
                "memory_resolver_id": self.MEMORY_RESOLVER_ID,
            })
            logger.warning("Runtime memory evidence projection rejected", extra={
                "correlation_id": ctx.correlation_id,
                "error_type": type(exc).__name__,
            })
            self._emitter.emit(
                RuntimeEventType.MEMORY_RECALL_COMPLETED,
                policy_decision_id=cognitive_context.policy_decision_id,
                memory_recall_count=0,
                metadata={"context_id": cognitive_context.context_id,
                          "resolver_id": self.MEMORY_RESOLVER_ID, "status": "failed",
                          "error_type": type(exc).__name__},
            )
            return
        cognitive_context.evidence.extend(resolved)
        self._mark_resolved(cognitive_context, EvidenceSource.MEMORY)

        degraded = bool(result.get("degraded")) or result.get("status") == "degraded"
        degradation_reason = result.get("degradation_reason") or result.get("reason")
        cognitive_context.metadata.update(
            {
                "memory_recall_status": result.get("status", "success"),
                "memory_recall_count": len(resolved),
                "memory_latency_ms": float(result.get("latency_ms") or 0.0),
                "memory_degraded": degraded,
                "memory_degradation_reason": degradation_reason,
                "memory_resolver_id": self.MEMORY_RESOLVER_ID,
                "memory_response_source": result.get("source", "neuro_recall"),
                "memory_provenance": tuple(result.get("provenance") or ()),
                "memory_retrieval_health": dict(result.get("retrieval_health") or {}),
            }
        )
        self._emitter.emit(
            RuntimeEventType.MEMORY_RECALL_COMPLETED,
            policy_decision_id=cognitive_context.policy_decision_id,
            memory_recall_count=len(resolved),
            metadata={
                "context_id": cognitive_context.context_id,
                "resolver_id": self.MEMORY_RESOLVER_ID,
                "status": cognitive_context.metadata["memory_recall_status"],
                "degraded": degraded,
            },
        )

    async def _resolve_continuity(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
        requirement: ContextRequirement,
    ) -> None:
        ctx = request.context
        try:
            service = (
                self._proactive_continuity_service
                or self._get_proactive_continuity_service()
            )
            agenda = await service.organize(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                limit=max(1, int(requirement.max_items or 5)),
                current_domains=tuple(
                    str(value)
                    for value in list(
                        requirement.metadata.get("current_domains") or []
                    )
                    if str(value).strip()
                ),
                current_request=self._latest_user_message(request),
            )
            candidates = list(agenda.candidates)
        except Exception as exc:
            logger.warning(
                "Runtime proactive continuity resolution failed: %s",
                exc,
                extra={
                    "correlation_id": ctx.correlation_id,
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                },
            )
            cognitive_context.metadata.update(
                {
                    "continuity_status": "failed",
                    "continuity_count": 0,
                    "continuity_degraded": True,
                    "continuity_reason": str(exc),
                }
            )
            return

        now = datetime.now(timezone.utc)
        cognitive_context.evidence.extend(
            [
                ContextEvidence(
                    evidence_id=candidate.candidate_id,
                    source=EvidenceSource.USER_MODEL,
                    content=candidate.subject,
                    source_ref=candidate.source_id,
                    relevance=candidate.utility,
                    confidence=candidate.confidence,
                    provenance=EvidenceProvenance(
                        source_ref=candidate.source_id,
                        source_record_id=candidate.source_id,
                        resolver_id="runtime.evidence.proactive_continuity",
                        resolver_version=self.RESOLVER_VERSION,
                        retrieval_method="proactive_continuity_ranker",
                        retrieved_at=now,
                        reason_codes=tuple(candidate.reason_codes),
                    ),
                    temporal=EvidenceTemporalContext(
                        effective_until=candidate.target_at,
                        as_of=now,
                    ),
                    contradiction=EvidenceContradiction(
                        status=EvidenceContradictionStatus.NONE,
                    ),
                    scope=EvidenceScope(
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        session_id=ctx.session_id,
                        conversation_id=ctx.conversation_id,
                    ),
                    metadata={
                        "candidate_id": candidate.candidate_id,
                        "source_type": candidate.source_type,
                        "source_id": candidate.source_id,
                        "utility": candidate.utility,
                        "urgency": candidate.urgency,
                        "interruption_cost": candidate.interruption_cost,
                        "reason_codes": list(candidate.reason_codes),
                        "resume_primary": (
                            agenda.primary_candidate_id == candidate.candidate_id
                        ),
                        "resume_ambiguous": agenda.ambiguous,
                        "execution_authorized": False,
                        **dict(candidate.metadata),
                    },
                )
                for candidate in candidates
            ]
        )
        self._mark_resolved(cognitive_context, EvidenceSource.USER_MODEL)
        cognitive_context.metadata.update(
            {
                "continuity_status": "success",
                "continuity_count": len(candidates),
                "continuity_degraded": False,
                "continuity_resolver_id": "runtime.evidence.proactive_continuity",
                "continuity_primary_candidate_id": agenda.primary_candidate_id,
                "continuity_ambiguous": agenda.ambiguous,
                "continuity_agenda_reason_codes": list(agenda.reason_codes),
            }
        )

    async def _resolve_conversation(
        self,
        request: ChatExecutionRequest,
        cognitive_context: CognitiveContext,
        requirement: ContextRequirement,
    ) -> None:
        ctx = request.context
        # RuntimePolicy already authorized this source for the authenticated
        # tenant/user. Ingress user assertions are conversation evidence, even
        # when the separate durable repository is unavailable. They are never
        # represented as persisted or server-verified facts.
        ingress = self._ingress_user_evidence(request, requirement)

        async def retain_authorized_ingress() -> None:
            if not ingress:
                return
            # Source permission is not conversation ownership. Independently
            # verify the current conversation's tenant/user when history fails.
            gateway = self._conversation_gateway or get_conversation_runtime_gateway()
            try:
                await gateway.require_owned_conversation(ctx)
            except Exception as exc:
                cognitive_context.metadata["conversation_ingress_fallback_denied"] = (
                    type(exc).__name__
                )
                return
            cognitive_context.evidence.extend(ingress)
            self._mark_resolved(cognitive_context, EvidenceSource.CONVERSATION)
            cognitive_context.metadata["conversation_ingress_evidence_count"] = len(ingress)

        try:
            gateway = self._conversation_gateway or get_conversation_runtime_gateway()
            result = await gateway.load_history(
                ctx,
                limit=max(0, int(requirement.max_items or 0)),
            )
        except PermissionError as exc:
            # Authorization/ownership errors are not dependency degradation.
            # Never promote request-local history under a rejected object scope.
            cognitive_context.metadata.update(
                {
                    "conversation_history_status": "rejected",
                    "conversation_history_count": 0,
                    "conversation_history_degraded": True,
                    "conversation_history_error_type": type(exc).__name__,
                    "conversation_resolver_id": self.CONVERSATION_RESOLVER_ID,
                }
            )
            return
        except Exception as exc:
            logger.warning(
                "Runtime durable conversation resolution failed: %s",
                exc,
                extra={
                    "correlation_id": ctx.correlation_id,
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "conversation_id": ctx.conversation_id,
                },
            )
            cognitive_context.metadata.update(
                {
                    "conversation_history_status": "failed",
                    "conversation_history_count": 0,
                    "conversation_history_degraded": True,
                    "conversation_history_reason": str(exc),
                    "conversation_resolver_id": self.CONVERSATION_RESOLVER_ID,
                }
            )
            await retain_authorized_ingress()
            return

        cognitive_context.metadata.update(result.to_metadata())
        cognitive_context.metadata["conversation_resolver_id"] = (
            self.CONVERSATION_RESOLVER_ID
        )

        if result.status in {"failed", "rejected"}:
            cognitive_context.metadata["conversation_history_degraded"] = True
            if result.error_type:
                cognitive_context.metadata["conversation_history_error_type"] = (
                    result.error_type
                )
            if result.status == "failed":
                await retain_authorized_ingress()
            return

        now = datetime.now(timezone.utc)
        resolved = [
            self._conversation_message_to_evidence(
                message,
                request=request,
                retrieved_at=now,
            )
            for message in result.messages
            if str(message.content or "").strip()
        ]
        cognitive_context.evidence.extend(resolved)
        self._mark_resolved(cognitive_context, EvidenceSource.CONVERSATION)
        cognitive_context.metadata["conversation_history_degraded"] = False
        cognitive_context.metadata["conversation_history_count"] = len(resolved)

        injected = self._materialize_conversation_history(request, result.messages)
        cognitive_context.metadata["conversation_history_injected"] = injected
        cognitive_context.metadata["conversation_history_injected_count"] = (
            len(result.messages) if injected else 0
        )

    @classmethod
    def _ingress_user_evidence(
        cls,
        request: ChatExecutionRequest,
        requirement: ContextRequirement,
    ) -> list[ContextEvidence]:
        """Project bounded user-supplied turns, not fabricated durable history.

        This method is reached only from the RuntimePolicy-authorized
        conversation resolver. Never elevate assistant/system/tool text into
        personal evidence; never accept externally supplied evidence IDs or
        tenant scope from message dictionaries.
        """
        ctx = request.context
        if not ctx.tenant_id or not ctx.user_id or not ctx.conversation_id:
            return []
        limit = max(0, min(int(requirement.max_items or 0), 40))
        if limit == 0:
            return []
        # The thin SSE ingress validates these bounded, user-authored turns.
        # Do not accept client-provided roles, IDs, tenant, or persistence state.
        recent = request.metadata.get("ingress_recent_user_messages", [])
        previous = (
            [(index, content) for index, content in enumerate(recent)
             if isinstance(content, str) and 0 < len(content.strip()) <= 500]
            if isinstance(recent, list) and len(recent) <= 12 else []
        )
        current = [
            (len(previous) + index, message.get("content"))
            for index, message in enumerate(request.messages)
            if isinstance(message, dict)
            and str(message.get("role", "")).lower() == "user"
            and isinstance(message.get("content"), str)
            and 0 < len(message["content"].strip()) <= 500
        ]
        candidates = (previous + current)[-limit:]
        now = datetime.now(timezone.utc)
        return [
            ContextEvidence(
                evidence_id=f"ingress:{ctx.correlation_id}:{index}",
                source=EvidenceSource.CONVERSATION,
                content=content.strip(),
                source_ref=None,
                relevance=1.0,
                confidence=1.0,
                provenance=EvidenceProvenance(
                    resolver_id=cls.CONVERSATION_RESOLVER_ID,
                    resolver_version=cls.RESOLVER_VERSION,
                    retrieval_method="authorized_request_ingress",
                    retrieved_at=now,
                    reason_codes=("user_supplied_not_durable",),
                ),
                temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
                contradiction=EvidenceContradiction(
                    status=EvidenceContradictionStatus.NONE,
                ),
                scope=EvidenceScope(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    conversation_id=ctx.conversation_id,
                ),
                metadata={"role": "user", "durable": False, "origin": "ingress"},
            )
            for index, content in candidates
        ]

    @staticmethod
    def _profile_fact_semantics(
        item_metadata: dict[str, Any],
        *,
        evidence_id: str,
        tenant_id: str,
        user_id: str,
    ) -> EvidenceFactSemantics | None:
        """Admit cardinality only from the current scoped profile projection.

        Ordinary memories, model text and unverified metadata cannot declare a
        SET and thereby turn incompatible singleton facts into valid answers.
        """
        custom = item_metadata.get("custom")
        if (
            item_metadata.get("source") != "postgres_profile_fact"
            or item_metadata.get("tenant_id") != tenant_id
            or item_metadata.get("user_id") != user_id
            or not isinstance(custom, dict)
            or custom.get("source_store") != "postgres"
            or str(custom.get("profile_fact_id") or "") != evidence_id
            or not str(custom.get("event_id") or "").strip()
        ):
            return None
        attribute = custom.get("attribute")
        if not isinstance(attribute, str) or not attribute or len(attribute) > 128:
            return None
        raw_scope = custom.get("semantic_scope", {})
        if not isinstance(raw_scope, dict) or len(raw_scope) > 8:
            return None
        normalized_scope: dict[str, str] = {}
        for key, value in raw_scope.items():
            if (
                key not in {
                    "scope", "domain", "facet", "project_id", "task_id",
                    "task_type", "location",
                }
                or not isinstance(value, (str, int, float))
                or isinstance(value, bool)
            ):
                return None
            # Use the canonical projection comparator's scalar normalization.
            normalized = str(value).strip().casefold()
            if len(normalized) > 160:
                return None
            if normalized:
                normalized_scope[key] = normalized
        try:
            cardinality = FactCardinality(str(custom.get("cardinality", "singleton")))
        except ValueError:
            return None
        if cardinality not in {
            FactCardinality.SINGLETON,
            FactCardinality.SET,
            FactCardinality.SCOPED_SINGLETON,
        }:
            return None
        return EvidenceFactSemantics(
            attribute=attribute,
            cardinality=cardinality,
            semantic_scope=tuple(sorted(normalized_scope.items())),
        )

    @staticmethod
    def _canonical_memory_event_origin(
        item: dict[str, Any],
        *,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, str] | None:
        """Project a typed durable origin without granting live authorization.

        NeuroRecall validates source records before selecting them. This
        second, scope-bound projection preserves the *event* UUID separately
        from assertion, profile-fact, procedure and other memory row IDs.
        It is intentionally not an ACL receipt or permission watermark.
        """
        import uuid

        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            return None
        if (
            metadata.get("tenant_id") != tenant_id
            or metadata.get("user_id") != user_id
        ):
            return None
        custom = metadata.get("custom")
        if not isinstance(custom, dict):
            return None
        provenance = custom.get("provenance")
        if not isinstance(provenance, dict):
            return None

        # Each entry is (canonical record type, row identity key, event key).
        # This is a projection of NeuroRecall's existing source contracts,
        # not a new source-authorizer registry.
        origins = {
            "postgres_memory_ledger": ("memory_assertion", "assertion_id", "event_id"),
            "postgres_profile_fact": ("profile_fact", "fact_id", "event_id"),
            "postgres_procedure": ("memory_procedure", "procedure_id", "source_event_id"),
            "postgres_user_goal": ("memory_user_goal", "goal_id", "event_id"),
            "postgres_open_loop": ("memory_open_loop", "open_loop_id", "event_id"),
            "postgres_prospective_memory": ("memory_prospective_item", "prospective_id", "event_id"),
            "postgres_graph": ("memory_event", "event_id", "event_id"),
        }
        source = metadata.get("source")
        contract = origins.get(source) if isinstance(source, str) else None
        if contract is None:
            return None
        record_type, identity_key, event_key = contract
        memory_id = str(item.get("id") or "")
        event_id = provenance.get(event_key)
        if (
            provenance.get("store") != "postgres"
            or provenance.get("record_type") != record_type
            or provenance.get(identity_key) != memory_id
            or custom.get(event_key) != event_id
            or not isinstance(event_id, str)
            or not isinstance(provenance.get("source_type"), str)
            or not provenance["source_type"].strip()
        ):
            return None
        try:
            event_uuid = uuid.UUID(event_id)
            record_uuid = uuid.UUID(memory_id)
        except (TypeError, ValueError):
            return None
        if str(event_uuid) != event_id or str(record_uuid) != memory_id:
            return None
        origin = {
            "event_id": event_id,
            "record_id": memory_id,
            "record_type": record_type,
            "source": source,
        }
        # This revision is copied from the retriever's MemoryEntry, not the
        # stored custom metadata. Its absence prevents later live attestation.
        revision = item.get("updated_at")
        if isinstance(revision, str):
            try:
                parsed_revision = datetime.fromisoformat(revision)
            except ValueError:
                return None
            if parsed_revision.tzinfo is None:
                parsed_revision = parsed_revision.replace(tzinfo=timezone.utc)
            origin["record_updated_at"] = parsed_revision.astimezone(
                timezone.utc
            ).isoformat()
        return origin

    @classmethod
    def _memory_item_to_evidence(
        cls,
        item: dict[str, Any],
        *,
        request: ChatExecutionRequest,
        retrieved_at: datetime,
    ) -> ContextEvidence:
        ctx = request.context
        item_metadata = dict(item.get("metadata") or {})
        evidence_id = str(item.get("id") or item_metadata.get("id") or "memory")
        timestamp = cls._coerce_datetime(item.get("timestamp"))
        expires_at = cls._coerce_datetime(item.get("expires_at"))
        contradiction = cls._contradiction_from_metadata(item_metadata)
        origin = cls._canonical_memory_event_origin(
            item, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
        )
        effective_from = None
        effective_until = None
        # Only canonical, scope-bound PostgreSQL record provenance may
        # supply these validity bounds. Arbitrary custom claims cannot.
        if origin and origin["record_type"] in {"profile_fact", "memory_assertion"}:
            custom = item_metadata["custom"]
            for key in ("valid_from", "valid_to"):
                raw = custom.get(key)
                parsed = cls._coerce_datetime(raw) if isinstance(raw, (str, datetime)) else None
                if raw is not None and parsed is None:
                    raise ValueError("invalid_canonical_memory_validity")
                if key == "valid_from":
                    effective_from = parsed
                else:
                    effective_until = parsed
            if effective_from is not None and effective_until is not None and effective_from >= effective_until:
                raise ValueError("invalid_canonical_memory_validity")

        return ContextEvidence(
            evidence_id=evidence_id,
            source=EvidenceSource.MEMORY,
            content=str(item.get("content") or item.get("result") or ""),
            source_ref=evidence_id,
            relevance=cls._coerce_float(item.get("similarity_score")),
            confidence=cls._coerce_float(item_metadata.get("confidence")),
            provenance=EvidenceProvenance(
                source_ref=evidence_id,
                source_record_id=evidence_id,
                resolver_id=cls.MEMORY_RESOLVER_ID,
                resolver_version=cls.RESOLVER_VERSION,
                retrieval_method="neuro_recall",
                retrieved_at=retrieved_at,
                reason_codes=("memory_recall",),
            ),
            temporal=EvidenceTemporalContext(
                observed_at=timestamp,
                as_of=retrieved_at,
                effective_from=effective_from,
                effective_until=effective_until,
                expires_at=expires_at,
            ),
            contradiction=contradiction,
            scope=EvidenceScope(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
            ),
            metadata={
                "memory_type": item.get("memory_type"),
                "memory_metadata": item_metadata,
                # A provenance candidate is not current consent authority.
                # Runtime publication must recheck this event at the ledger.
                "canonical_event_origin": origin,
            },
            fact_semantics=cls._profile_fact_semantics(
                item_metadata,
                evidence_id=evidence_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
            ),
        )

    @classmethod
    def _conversation_message_to_evidence(
        cls,
        message: Any,
        *,
        request: ChatExecutionRequest,
        retrieved_at: datetime,
    ) -> ContextEvidence:
        ctx = request.context
        evidence_id = str(message.id)
        observed_at = cls._coerce_datetime(message.created_at)
        return ContextEvidence(
            evidence_id=evidence_id,
            source=EvidenceSource.CONVERSATION,
            content=str(message.content or ""),
            source_ref=evidence_id,
            relevance=1.0,
            confidence=1.0,
            provenance=EvidenceProvenance(
                source_ref=evidence_id,
                source_record_id=evidence_id,
                resolver_id=cls.CONVERSATION_RESOLVER_ID,
                resolver_version=cls.RESOLVER_VERSION,
                retrieval_method="conversation_repository",
                retrieved_at=retrieved_at,
                reason_codes=("durable_transcript",),
            ),
            temporal=EvidenceTemporalContext(
                observed_at=observed_at,
                as_of=retrieved_at,
            ),
            contradiction=EvidenceContradiction(
                status=EvidenceContradictionStatus.NONE,
            ),
            scope=EvidenceScope(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
            ),
            metadata={
                "role": str(message.role),
                "message_metadata": dict(message.metadata or {}),
            },
        )

    @staticmethod
    def _materialize_conversation_history(
        request: ChatExecutionRequest,
        messages: tuple[Any, ...],
    ) -> bool:
        """Prepend durable history only when ingress did not already supply it."""
        if not messages:
            return False

        supplied_roles = [
            str(message.get("role", "")).lower()
            for message in request.messages
            if isinstance(message, dict)
        ]
        if "assistant" in supplied_roles:
            request.metadata["conversation_history_source"] = "ingress"
            return False

        durable_messages = [
            {
                "role": str(message.role).lower(),
                "content": str(message.content),
            }
            for message in messages
            if str(message.role).lower() in {"user", "assistant"}
            and str(message.content or "").strip()
        ]
        if not durable_messages:
            return False

        leading_system: list[dict[str, Any]] = []
        remainder = list(request.messages)
        while remainder and str(remainder[0].get("role", "")).lower() == "system":
            leading_system.append(remainder.pop(0))

        request.messages = [*leading_system, *durable_messages, *remainder]
        request.metadata["conversation_history_source"] = "canonical_repository"
        request.metadata["conversation_history_materialized"] = True
        return True

    @staticmethod
    def _mark_resolved(
        cognitive_context: CognitiveContext,
        source: EvidenceSource,
    ) -> None:
        cognitive_context.unresolved_sources = [
            value
            for value in cognitive_context.unresolved_sources
            if value != source.value
        ]

    @staticmethod
    def _latest_user_message(request: ChatExecutionRequest) -> str:
        for message in reversed(request.messages):
            if str(message.get("role", "")).lower() == "user":
                return str(message.get("content", ""))
        if request.messages:
            return str(request.messages[-1].get("content", ""))
        return ""

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _contradiction_from_metadata(
        metadata: dict[str, Any],
    ) -> EvidenceContradiction:
        raw_status = str(metadata.get("contradiction_status") or "unknown").lower()
        try:
            status = EvidenceContradictionStatus(raw_status)
        except ValueError:
            status = EvidenceContradictionStatus.UNKNOWN

        conflicting_ids = metadata.get("conflicting_evidence_ids") or ()
        if isinstance(conflicting_ids, str):
            conflicting_ids = (conflicting_ids,)

        reason_codes = metadata.get("contradiction_reason_codes") or ()
        if isinstance(reason_codes, str):
            reason_codes = (reason_codes,)

        return EvidenceContradiction(
            status=status,
            conflicting_evidence_ids=tuple(str(value) for value in conflicting_ids),
            reason_codes=tuple(str(value) for value in reason_codes),
            resolution_ref=(
                str(metadata["contradiction_resolution_ref"])
                if metadata.get("contradiction_resolution_ref") is not None
                else None
            ),
        )

    @staticmethod
    def _get_proactive_continuity_service() -> Any:
        from ai_karen_engine.core.intelligence.proactive import (
            ProactiveContinuityService,
        )
        from ai_karen_engine.platform.personalization.proactive_repository import (
            PostgresProactiveContinuityRepository,
        )

        return ProactiveContinuityService(
            PostgresProactiveContinuityRepository()
        )

    @staticmethod
    def _get_memory_manager() -> Any:
        from ai_karen_engine.core.memory import get_memory_manager

        return get_memory_manager()


__all__ = ["RuntimeEvidenceResolver"]
