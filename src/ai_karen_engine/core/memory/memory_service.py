"""
Enhanced Memory Service for Web UI Integration.
Extends the existing MemoryManager with web UI specific features and query methods.

This service is being refactored to use the new unified memory service.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from ai_karen_engine.core.logging import get_logger

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import Field

from ai_karen_engine.interfaces.ui.memory_models import (
    UISource,
    WebUIMemoryEntry,
    WebUIMemoryQuery,
)

logger = get_logger(__name__)



class MemoryContextBuilder:
    """Builds conversation context from relevant memories."""

    def __init__(self, memory_service: "WebUIMemoryService"):
        self.memory_service = memory_service
        self.max_context_tokens = 2000  # Approximate token limit for context
        self.context_weights = {
            UIMemoryType.FACT: 1.0,
            UIMemoryType.PREFERENCE: 0.9,
            UIMemoryType.CONTEXT: 0.8,
            UIMemoryType.CONVERSATION: 0.7,
            UIMemoryType.INSIGHT: 0.6,
            UIMemoryType.GENERAL: 0.5,
        }

    async def build_context(
        self,
        tenant_id: str | uuid.UUID,
        query: str,
        user_id: str,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Build conversation context from relevant memories using NLP-enhanced retrieval."""
        try:
            # Use NLP to analyze the query for better context building
            query_analysis = await self._analyze_query_with_nlp(query)

            # Query for relevant memories with different types
            memory_query = WebUIMemoryQuery(
                text=query,
                user_id=user_id,
                session_id=session_id,
                conversation_id=conversation_id,
                top_k=20,  # Get more memories for context building
                similarity_threshold=0.6,  # Lower threshold for context
                curated_only=True,
            )

            memories = await self.memory_service.query_memories(tenant_id, memory_query)

            # Enhance memory ranking using NLP analysis
            memories = await self._enhance_memory_ranking_with_nlp(
                memories, query_analysis
            )

            # Group memories by type
            memories_by_type = {}
            for memory in memories:
                mem_type = memory.memory_type
                if mem_type not in memories_by_type:
                    memories_by_type[mem_type] = []
                memories_by_type[mem_type].append(memory)

            # Build weighted context
            context_parts = []
            total_tokens = 0

            # Process memories by importance (facts first, then preferences, etc.)
            for mem_type in sorted(
                self.context_weights.keys(),
                key=lambda x: self.context_weights[x],
                reverse=True,
            ):
                if mem_type not in memories_by_type:
                    continue

                type_memories = memories_by_type[mem_type]
                # Sort by enhanced importance score and similarity
                type_memories.sort(
                    key=lambda m: (
                        getattr(m, "nlp_relevance_score", m.importance_score),
                        m.similarity_score or 0,
                    ),
                    reverse=True,
                )

                for memory in type_memories:
                    # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                    memory_tokens = len(memory.content) // 4
                    if total_tokens + memory_tokens > self.max_context_tokens:
                        break

                    context_parts.append(
                        {
                            "id": memory.id,
                            "type": mem_type.value,
                            "memory_class": (memory.metadata or {}).get("memory_class"),
                            "content": memory.content,
                            "importance": memory.importance_score,
                            "similarity": memory.similarity_score,
                            "nlp_relevance": getattr(
                                memory, "nlp_relevance_score", None
                            ),
                            "timestamp": memory.timestamp,
                            "tags": memory.tags,
                            "metadata": memory.metadata,
                        }
                    )
                    total_tokens += memory_tokens

                if total_tokens >= self.max_context_tokens:
                    break

            # Get conversation history if conversation_id provided
            conversation_context = None
            if conversation_id:
                conversation_context = await self._get_conversation_context(
                    tenant_id, conversation_id
                )

            return {
                "memories": context_parts,
                "total_memories": len(context_parts),
                "memory_types_found": list(memories_by_type.keys()),
                "conversation_context": conversation_context,
                "query_analysis": query_analysis,
                "context_metadata": {
                    "query": query,
                    "user_id": user_id,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "curated_recall": memory_query.curated_only,
                    "curated_memory_classes": list(memory_query.memory_classes)
                    if memory_query.curated_only
                    else [],
                    "total_tokens_estimate": total_tokens,
                    "generated_at": datetime.utcnow().isoformat(),
                },
            }

        except Exception as e:
            logger.error(f"Failed to build context for tenant {tenant_id}: {e}")
            return {
                "memories": [],
                "total_memories": 0,
                "memory_types_found": [],
                "conversation_context": None,
                "error": str(e),
            }

    async def _analyze_query_with_nlp(self, query: str) -> dict[str, Any]:
        """Analyze query using NLP to extract key information for better context building."""
        try:
            # Import spaCy service for query analysis
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
            spacy_service = SpacyService()

            # Get comprehensive NLP analysis of the query
            parsed_query = await spacy_service.parse_message(query)
            linguistic_features = (
                await spacy_service.get_linguistic_features(query)
            )

            # Extract key entities and their types
            key_entities = []
            for entity_text, entity_label in parsed_query.entities:
                key_entities.append(
                    {
                        "text": entity_text,
                        "label": entity_label,
                        "importance": 1.0
                        if entity_label in ["PERSON", "ORG", "GPE"]
                        else 0.8,
                    }
                )

            # Extract important nouns and verbs
            important_tokens = []
            for token, pos in parsed_query.pos_tags:
                if pos in ["NOUN", "PROPN", "VERB"] and len(token) > 2:
                    important_tokens.append(
                        {
                            "text": token,
                            "pos": pos,
                            "importance": 1.0 if pos in ["PROPN", "NOUN"] else 0.7,
                        }
                    )

            return {
                "entities": key_entities,
                "important_tokens": important_tokens,
                "sentences": parsed_query.sentences,
                "noun_phrases": parsed_query.noun_phrases,
                "linguistic_features": linguistic_features,
                "query_complexity": len(parsed_query.dependencies),
                "used_fallback": parsed_query.used_fallback,
            }

        except Exception as e:
            logger.warning(f"Failed to analyze query with NLP: {e}")
            # Return basic analysis as fallback
            return {
                "entities": [],
                "important_tokens": [],
                "sentences": [query],
                "noun_phrases": [],
                "linguistic_features": {},
                "query_complexity": 0,
                "used_fallback": True,
            }

    async def _enhance_memory_ranking_with_nlp(
        self, memories: list["WebUIMemoryEntry"], query_analysis: dict[str, Any]
    ) -> list["WebUIMemoryEntry"]:
        """Enhance memory ranking using NLP analysis of query and memory content."""
        try:
            # Import spaCy service for memory analysis
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
            spacy_service = SpacyService()

            query_entities = {
                entity["text"].lower() for entity in query_analysis.get("entities", [])
            }
            query_tokens = {
                token["text"].lower()
                for token in query_analysis.get("important_tokens", [])
            }

            enhanced_memories = []
            for memory in memories:
                try:
                    # Analyze memory content
                    memory_entities = (
                        await spacy_service.extract_entities(
                            memory.content
                        )
                    )
                    memory_entity_texts = {
                        entity[0].lower() for entity in memory_entities
                    }

                    # Calculate NLP-based relevance score
                    entity_overlap = len(
                        query_entities.intersection(memory_entity_texts)
                    )

                    # Simple token overlap (could be enhanced with semantic similarity)
                    memory_tokens = set(memory.content.lower().split())
                    token_overlap = len(query_tokens.intersection(memory_tokens))

                    # Calculate enhanced relevance score
                    base_score = memory.similarity_score or 0.0
                    entity_boost = entity_overlap * 0.2  # Boost for entity matches
                    token_boost = token_overlap * 0.1  # Boost for token matches

                    nlp_relevance_score = base_score + entity_boost + token_boost

                    # Add the enhanced score as an attribute
                    memory.nlp_relevance_score = min(
                        nlp_relevance_score, 1.0
                    )  # Cap at 1.0
                    enhanced_memories.append(memory)

                except Exception as e:
                    logger.warning(
                        f"Failed to enhance ranking for memory {memory.id}: {e}"
                    )
                    # Keep original memory without enhancement
                    memory.nlp_relevance_score = memory.similarity_score or 0.0
                    enhanced_memories.append(memory)

            return enhanced_memories

        except Exception as e:
            logger.warning(f"Failed to enhance memory ranking with NLP: {e}")
            # Return original memories without enhancement
            for memory in memories:
                memory.nlp_relevance_score = memory.similarity_score or 0.0
            return memories

    async def _get_conversation_context(
        self, tenant_id: str | uuid.UUID, conversation_id: str
    ) -> dict[str, Any] | None:
        """Get conversation context from database."""
        try:
            if self.memory_service.db_client:
                async with self.memory_service.db_client.get_async_session() as session:
                    result = await session.execute(
                        select(TenantConversation).where(
                            TenantConversation.id == uuid.UUID(conversation_id)
                        )
                    )
                    conversation = result.scalar_one_or_none()

                    if conversation:
                        return {
                            "title": conversation.title,
                            "summary": conversation.summary,
                            "ui_context": conversation.ui_context,
                            "ai_insights": conversation.ai_insights,
                            "user_settings": conversation.user_settings,
                            "tags": conversation.tags,
                            "last_updated": conversation.updated_at.isoformat(),
                        }

                    return None

        except Exception as e:
            logger.error(f"Failed to get conversation context: {e}")
            return None


class WebUIMemoryService(UnifiedMemoryService):
    """Enhanced memory service with web UI specific features.
    
    This class now extends the UnifiedMemoryService to provide backward compatibility
    while leveraging the new unified architecture.
    """

    def __init__(
        self,
        db_client: MultiTenantPostgresClient | None = None,
        embedding_manager: EmbeddingManager | None = None,
        redis_client: Any | None = None,
        policy_manager: Any | None = None,
        base_memory_manager: MemoryManager | None = None,
    ):
        """Initialize the production Web UI memory service on top of the unified service."""
        if base_memory_manager is None:
            db_client = db_client or MultiTenantPostgresClient()
            embedding_manager = embedding_manager or EmbeddingManager()
        else:
            db_client = base_memory_manager.db_client
            embedding_manager = base_memory_manager.embedding_manager
            redis_client = getattr(base_memory_manager, "redis_client", redis_client)

        super().__init__(
            db_client=db_client,
            embedding_manager=embedding_manager,
            redis_client=redis_client,
            policy_manager=policy_manager,
        )

        self.base_manager = base_memory_manager or self.base_manager
        self.db_client = db_client
        self.context_builder = MemoryContextBuilder(self)

        # Web UI specific configuration
        self.default_importance_score = 5
        self.auto_tag_enabled = True
        self.fact_extraction_enabled = True

        # Performance metrics
        self.web_ui_metrics = {
            "context_builds": 0,
            "web_ui_queries": 0,
            "memory_confirmations": 0,
            "auto_tags_generated": 0,
            "facts_extracted": 0,
        }

    @staticmethod
    def _infer_web_memory_type(
        web_data: dict[str, Any],
        base_memory: MemoryEntry,
    ) -> UIMemoryType:
        """Map stored curated metadata back onto the web UI memory taxonomy."""
        explicit_type = web_data.get("memory_type")
        if explicit_type:
            try:
                return UIMemoryType(str(explicit_type))
            except Exception:
                pass

        metadata = getattr(base_memory, "metadata", {}) or {}
        memory_class = str(metadata.get("memory_class") or "").strip()
        if memory_class == "user_fact":
            return UIMemoryType.PREFERENCE
        if memory_class == "project_fact":
            return UIMemoryType.FACT
        if memory_class == "episodic":
            return UIMemoryType.CONVERSATION
        if memory_class == "semantic_long_term":
            return UIMemoryType.INSIGHT

        fallback_type = metadata.get("memory_type") or metadata.get("type")
        if fallback_type:
            try:
                return UIMemoryType(str(fallback_type))
            except Exception:
                pass

        return UIMemoryType.GENERAL

    async def build_context(
        self,
        *,
        tenant_id: str | uuid.UUID | None = None,
        user_id: str,
        query: str | None = None,
        prompt: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """LangGraph-compatible context builder backed by the production memory service."""
        resolved_tenant_id: str | uuid.UUID = (
            tenant_id or conversation_id or session_id or user_id
        )
        return await self.build_conversation_context(
            tenant_id=resolved_tenant_id,
            query=query or prompt or "",
            user_id=user_id,
            session_id=session_id,
            conversation_id=conversation_id,
        )

    async def store_web_ui_memory(
        self,
        tenant_id: str | uuid.UUID,
        content: str,
        user_id: str,
        ui_source: UISource,
        session_id: str | None = None,
        conversation_id: str | None = None,
        memory_type: UIMemoryType = UIMemoryType.GENERAL,
        tags: list[str] | None = None,
        importance_score: int | None = None,
        ai_generated: bool = False,
        metadata: dict[str, Any] | None = None,
        ttl_hours: int | None = None,
        tenant_filters: dict[str, Any] | None = None,
    ) -> str | None:
        """Store memory with web UI specific features."""
        if not self.base_manager:
            logger.warning("Memory manager unavailable - skipping memory store")
            return None
        try:
            # Auto-generate tags if enabled
            if self.auto_tag_enabled and not tags:
                tags = await self._generate_auto_tags(content, memory_type)
                if tags:
                    self.web_ui_metrics["auto_tags_generated"] += 1

            # Extract facts if enabled and memory type is appropriate
            extracted_facts = []
            if (
                self.fact_extraction_enabled
                and memory_type in [UIMemoryType.FACT, UIMemoryType.GENERAL]
                and not ai_generated
            ):
                extracted_facts = await self._extract_facts(content)
                if extracted_facts:
                    self.web_ui_metrics["facts_extracted"] += 1

            # Prepare metadata with web UI fields
            web_ui_metadata = {
                "ui_source": ui_source.value,
                "conversation_id": conversation_id,
                "memory_type": memory_type.value,
                "importance_score": importance_score or self.default_importance_score,
                "ai_generated": ai_generated,
                "user_confirmed": not ai_generated,  # AI generated memories need confirmation
                "extracted_facts": extracted_facts,
                "access_count": 0,
            }

            if metadata:
                web_ui_metadata.update(metadata)

            # Store using base manager with correct parameters
            # Include user_id, session_id, tags, and ttl_hours in metadata
            web_ui_metadata.update(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "tags": tags or [],
                    "ttl_hours": ttl_hours,
                }
            )

            memory_id = await self.base_manager.store_memory(
                tenant_id=tenant_id,
                content=content,
                scope=f"user:{user_id}",  # Use user_id as scope
                kind=memory_type.value,  # Use memory_type as kind
                metadata=web_ui_metadata,
            )

            # Update database with web UI specific fields
            if memory_id:
                await self._update_web_ui_fields(tenant_id, memory_id, web_ui_metadata)

            return memory_id

        except Exception as e:
            logger.error(f"Failed to store web UI memory: {e}")
            raise

    async def query_memories(
        self,
        tenant_id: str | uuid.UUID,
        query: WebUIMemoryQuery,
        tenant_filters: dict[str, Any] | None = None,
    ) -> list[WebUIMemoryEntry]:
        """Query memories with web UI specific filtering."""
        if not self.base_manager:
            logger.warning("Memory manager unavailable - returning empty results")
            return []
        try:
            self.web_ui_metrics["web_ui_queries"] += 1

            # Convert to base query for vector search
            base_query = query.to_memory_query()
            base_memories = await self.base_manager.query_memories(
                tenant_id, base_query
            )
            if query.curated_only:
                base_memories = filter_curated_memories(
                    base_memories,
                    allowed_classes=query.memory_classes,
                )

            # Get additional web UI data from database
            memory_ids = [m.id for m in base_memories]
            web_ui_data = await self._get_web_ui_memory_data(tenant_id, memory_ids)

            # Convert to WebUIMemoryEntry with filtering
            web_ui_memories = []
            for base_memory in base_memories:
                web_data = web_ui_data.get(base_memory.id, {})

                # Apply web UI specific filters
                if not self._passes_web_ui_filters(web_data, query):
                    continue

                # Update access count
                await self._increment_access_count(tenant_id, base_memory.id)

                web_ui_memory = WebUIMemoryEntry(
                    id=base_memory.id,
                    content=base_memory.content,
                    embedding=base_memory.embedding,
                    metadata=base_memory.metadata,
                    timestamp=base_memory.timestamp,
                    ttl=base_memory.ttl,
                    user_id=base_memory.user_id,
                    session_id=base_memory.session_id,
                    tags=base_memory.tags,
                    similarity_score=base_memory.similarity_score,
                    # Web UI specific fields
                    ui_source=UISource(web_data.get("ui_source", "api")),
                    conversation_id=web_data.get("conversation_id"),
                    memory_type=self._infer_web_memory_type(web_data, base_memory),
                    importance_score=web_data.get("importance_score", 5),
                    access_count=web_data.get("access_count", 0),
                    last_accessed=web_data.get("last_accessed"),
                    ai_generated=web_data.get("ai_generated", False),
                    user_confirmed=web_data.get("user_confirmed", True),
                )

                web_ui_memories.append(web_ui_memory)

            return web_ui_memories

        except Exception as e:
            logger.error(f"Failed to query web UI memories: {e}")
            raise

    async def build_conversation_context(
        self,
        tenant_id: str | uuid.UUID,
        query: str,
        user_id: str,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Build conversation context from relevant memories."""
        self.web_ui_metrics["context_builds"] += 1
        return await self.context_builder.build_context(
            tenant_id, query, user_id, session_id, conversation_id
        )

    async def confirm_memory(
        self, tenant_id: str | uuid.UUID, memory_id: str, confirmed: bool = True
    ) -> bool:
        """Confirm or reject an AI-generated memory."""
        try:
            if self.db_client:
                async with self.db_client.get_async_session() as session:
                    await session.execute(
                        update(TenantMemoryEntry)
                        .where(TenantMemoryEntry.vector_id == memory_id)
                        .values(user_confirmed=confirmed)
                    )
                    await session.commit()

                    if confirmed:
                        self.web_ui_metrics["memory_confirmations"] += 1

                    return True

        except Exception as e:
            logger.error(f"Failed to confirm memory {memory_id}: {e}")
            return False

    async def update_memory_importance(
        self, tenant_id: str | uuid.UUID, memory_id: str, importance_score: int
    ) -> bool:
        """Update memory importance score."""
        if not (1 <= importance_score <= 10):
            raise ValueError("Importance score must be between 1 and 10")

        try:
            if self.db_client:
                async with self.db_client.get_async_session() as session:
                    await session.execute(
                        update(TenantMemoryEntry)
                        .where(TenantMemoryEntry.vector_id == memory_id)
                        .values(importance_score=importance_score)
                    )
                    await session.commit()
                    return True

        except Exception as e:
            logger.error(f"Failed to update memory importance: {e}")
            return False

    async def get_memory_analytics(
        self,
        tenant_id: str | uuid.UUID,
        user_id: str | None = None,
        time_range: tuple[datetime, datetime] | None = None,
    ) -> dict[str, Any]:
        """Get memory analytics for web UI dashboard."""
        try:
            if self.db_client:
                async with self.db_client.get_async_session() as session:
                    # Base query
                    query_conditions = []
                    if user_id:
                        query_conditions.append(
                            TenantMemoryEntry.user_id == uuid.UUID(user_id)
                        )
                    if time_range:
                        query_conditions.append(
                            TenantMemoryEntry.created_at >= time_range[0]
                        )
                        query_conditions.append(
                            TenantMemoryEntry.created_at <= time_range[1]
                        )

                    base_query = select(TenantMemoryEntry)
                    if query_conditions:
                        base_query = base_query.where(and_(*query_conditions))

                    # Get all memories for analysis
                    result = await session.execute(base_query)
                    memories = result.fetchall()

                    # Analyze memories
                    analytics = {
                        "total_memories": len(memories),
                        "memories_by_type": {},
                        "memories_by_ui_source": {},
                        "memories_by_importance": {},
                        "ai_generated_count": 0,
                        "user_confirmed_count": 0,
                        "average_importance": 0,
                        "most_accessed_memories": [],
                        "recent_activity": [],
                        "tag_frequency": {},
                        "web_ui_metrics": self.web_ui_metrics.copy(),
                    }

                    if not memories:
                        return analytics

                    # Process memories
                    importance_sum = 0
                    for memory in memories:
                        # Memory type distribution
                        mem_type = memory.memory_type or "general"
                        analytics["memories_by_type"][mem_type] = (
                            analytics["memories_by_type"].get(mem_type, 0) + 1
                        )

                        # UI source distribution
                        ui_source = memory.ui_source or "unknown"
                        analytics["memories_by_ui_source"][ui_source] = (
                            analytics["memories_by_ui_source"].get(ui_source, 0) + 1
                        )

                        # Importance distribution
                        importance = memory.importance_score or 5
                        analytics["memories_by_importance"][str(importance)] = (
                            analytics["memories_by_importance"].get(str(importance), 0) + 1
                        )
                        importance_sum += importance

                        # AI generated vs user confirmed
                        if memory.ai_generated:
                            analytics["ai_generated_count"] += 1
                        if memory.user_confirmed:
                            analytics["user_confirmed_count"] += 1

                        # Tag frequency
                        if memory.tags:
                            for tag in memory.tags:
                                analytics["tag_frequency"][tag] = (
                                    analytics["tag_frequency"].get(tag, 0) + 1
                                )

                    analytics["average_importance"] = importance_sum / len(memories)

                    # Get most accessed memories
                    most_accessed_query = base_query.order_by(
                        desc(TenantMemoryEntry.access_count)
                    ).limit(10)
                    most_accessed_result = await session.execute(most_accessed_query)
                    analytics["most_accessed_memories"] = [
                        {
                            "id": mem.vector_id,
                            "content": mem.content[:100] + "..."
                            if len(mem.content) > 100
                            else mem.content,
                            "access_count": mem.access_count,
                            "importance_score": mem.importance_score,
                        }
                        for mem in most_accessed_result.fetchall()
                    ]

                    # Recent activity (last 24 hours)
                    recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                    recent_query = base_query.where(
                        TenantMemoryEntry.created_at > recent_cutoff
                    )
                    recent_result = await session.execute(recent_query)
                    analytics["recent_activity"] = [
                        {
                            "id": mem.vector_id,
                            "content": mem.content[:50] + "..."
                            if len(mem.content) > 50
                            else mem.content,
                            "memory_type": mem.memory_type,
                            "created_at": mem.created_at.isoformat(),
                        }
                        for mem in recent_result.fetchall()
                    ]

                    return analytics

        except Exception as e:
            logger.error(f"Failed to get memory analytics: {e}")
            return {"error": str(e)}

    async def _update_web_ui_fields(
        self,
        tenant_id: str | uuid.UUID,
        memory_id: str,
        web_ui_metadata: dict[str, Any],
    ):
        """Compatibility shim for older schemas.

        The current TenantMemoryEntry model stores web UI fields inside JSON metadata.
        Base memory persistence already writes those fields, so no follow-up SQL update
        is required here.
        """
        return

    async def _get_web_ui_memory_data(
        self, tenant_id: str | uuid.UUID, memory_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Get web UI specific data for memory entries."""
        try:
            if not memory_ids:
                return {}

            if self.db_client:
                valid_ids = []
                for memory_id in memory_ids:
                    try:
                        valid_ids.append(uuid.UUID(str(memory_id)))
                    except Exception:
                        continue

                if not valid_ids:
                    return {}

                async with self.db_client.get_async_session() as session:
                    result = await session.execute(
                        select(TenantMemoryEntry).where(
                            TenantMemoryEntry.id.in_(valid_ids)
                        )
                    )

                    web_ui_data = {}
                    for memory in result.scalars().all():
                        item_metadata = (
                            memory.item_metadata
                            if isinstance(memory.item_metadata, dict)
                            else {}
                        )
                        web_ui_data[str(memory.id)] = {
                            "ui_source": item_metadata.get("ui_source"),
                            "conversation_id": item_metadata.get("conversation_id"),
                            "memory_type": item_metadata.get("memory_type", memory.kind),
                            "importance_score": item_metadata.get("importance_score", 5),
                            "access_count": item_metadata.get("access_count", 0),
                            "last_accessed": item_metadata.get("last_accessed"),
                            "ai_generated": item_metadata.get("ai_generated", False),
                            "user_confirmed": item_metadata.get("user_confirmed", True),
                        }

                    return web_ui_data

        except Exception as e:
            logger.error(f"Failed to get web UI memory data: {e}")
            return {}

    def _passes_web_ui_filters(
        self, web_data: dict[str, Any], query: WebUIMemoryQuery
    ) -> bool:
        """Check if memory passes web UI specific filters."""
        # UI source filter
        if query.ui_source and web_data.get("ui_source") != query.ui_source.value:
            return False

        # Memory type filter
        if query.memory_types:
            memory_type = web_data.get("memory_type", "general")
            if memory_type not in [mt.value for mt in query.memory_types]:
                return False

        # Importance range filter
        if query.importance_range:
            importance = web_data.get("importance_score", 5)
            if not (
                query.importance_range[0] <= importance <= query.importance_range[1]
            ):
                return False

        # User confirmed filter
        if query.only_user_confirmed and not web_data.get("user_confirmed", True):
            return False

        # AI generated filter
        if query.only_ai_generated and not web_data.get("ai_generated", False):
            return False

        # Conversation filter
        if (
            query.conversation_id
            and web_data.get("conversation_id") != query.conversation_id
        ):
            return False

        return True

    async def _increment_access_count(
        self, tenant_id: str | uuid.UUID, memory_id: str
    ):
        """Increment access count for a memory.

        Access metrics are not materialized as dedicated columns in the current
        schema, so this is a no-op compatibility shim.
        """
        return

    async def _generate_auto_tags(
        self, content: str, memory_type: UIMemoryType
    ) -> list[str]:
        """Generate automatic tags for memory content using spaCy NLP."""
        try:
            # Import spaCy service for entity-based tagging
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
            spacy_service = SpacyService()

            tags = []

            # Extract entities and use them as tags
            entities = await spacy_service.extract_entities(content)
            for entity_text, entity_label in entities:
                # Add entity labels as tags
                tags.append(entity_label.lower())
                # Add entity text as tag if it's short enough
                if len(entity_text) <= 20:
                    tags.append(entity_text.lower().replace(" ", "_"))

            # Get linguistic features for additional tagging
            features = await spacy_service.get_linguistic_features(
                content
            )

            # Add POS-based tags
            pos_distribution = features.get("pos_distribution", {})
            if pos_distribution.get("VERB", 0) > pos_distribution.get("NOUN", 0):
                tags.append("action_oriented")
            elif pos_distribution.get("NOUN", 0) > 2:
                tags.append("fact_heavy")

            # Add sentiment-based tags (basic keyword matching)
            positive_keywords = [
                "like",
                "love",
                "enjoy",
                "prefer",
                "good",
                "great",
                "excellent",
            ]
            negative_keywords = ["dislike", "hate", "avoid", "bad", "terrible", "awful"]

            content_lower = content.lower()
            if any(keyword in content_lower for keyword in positive_keywords):
                tags.append("positive")
            if any(keyword in content_lower for keyword in negative_keywords):
                tags.append("negative")

            # Fallback to basic keyword extraction if spaCy fails
            if not tags:
                keywords = [
                    "important",
                    "remember",
                    "fact",
                    "preference",
                    "like",
                    "dislike",
                    "always",
                    "never",
                ]
                for keyword in keywords:
                    if keyword.lower() in content_lower:
                        tags.append(keyword)

            # Add memory type as tag
            tags.append(memory_type.value)

            # Add length-based tags
            if len(content) > 200:
                tags.append("detailed")
            elif len(content) < 50:
                tags.append("brief")

            # Add sentence count based tags
            sentence_count = features.get("sentence_count", 1)
            if sentence_count > 3:
                tags.append("multi_sentence")
            elif sentence_count == 1:
                tags.append("single_sentence")

            return list(set(tags))  # Remove duplicates

        except Exception as e:
            logger.warning(
                f"Failed to generate auto tags using spaCy, using fallback: {e}"
            )
            # Fallback to simple keyword extraction
            tags = []
            keywords = [
                "important",
                "remember",
                "fact",
                "preference",
                "like",
                "dislike",
                "always",
                "never",
            ]
            content_lower = content.lower()
            for keyword in keywords:
                if keyword in content_lower:
                    tags.append(keyword)

            tags.append(memory_type.value)

            if len(content) > 200:
                tags.append("detailed")
            elif len(content) < 50:
                tags.append("brief")

            return list(set(tags))

    async def _extract_facts(self, content: str) -> list[str]:
        """Extract facts from memory content using spaCy NLP."""
        try:
            # Import spaCy service for fact extraction
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
            spacy_service = SpacyService()

            # Use spaCy service to extract facts
            facts = await spacy_service.extract_facts(content)

            # Convert fact dictionaries to strings for storage
            fact_strings = []
            for fact in facts:
                if fact["type"] == "entity":
                    fact_strings.append(f"{fact['entity']} is a {fact['label']}")
                elif fact["type"] == "relationship":
                    fact_strings.append(
                        f"{fact['subject']} {fact['relation']} {fact['object']}"
                    )

            # Fallback to simple pattern matching if spaCy extraction fails
            if not fact_strings:
                fact_patterns = [
                    "I am",
                    "I like",
                    "I dislike",
                    "I prefer",
                    "My name is",
                    "I work at",
                    "I live in",
                    "I was born",
                    "I studied",
                ]

                for pattern in fact_patterns:
                    if pattern.lower() in content.lower():
                        # Extract sentence containing the pattern
                        sentences = content.split(".")
                        for sentence in sentences:
                            if pattern.lower() in sentence.lower():
                                fact_strings.append(sentence.strip())
                                break

            return fact_strings

        except Exception as e:
            logger.warning(f"Failed to extract facts using spaCy, using fallback: {e}")
            # Fallback to simple pattern matching
            facts = []
            fact_patterns = [
                "I am",
                "I like",
                "I dislike",
                "I prefer",
                "My name is",
                "I work at",
                "I live in",
                "I was born",
                "I studied",
            ]

            for pattern in fact_patterns:
                if pattern.lower() in content.lower():
                    sentences = content.split(".")
                    for sentence in sentences:
                        if pattern.lower() in sentence.lower():
                            facts.append(sentence.strip())
                            break

            return facts

    def get_metrics(self) -> dict[str, Any]:
        """Get combined metrics from base manager and web UI service."""
        base_metrics = self.base_manager.metrics.copy() if self.base_manager else {}
        base_metrics.update(self.web_ui_metrics)
        return base_metrics


__all__ = [
    "MemoryContextBuilder",
    "MemoryService",
    "UIMemoryType",
    "UISource",
    "WebUIMemoryEntry",
    "WebUIMemoryQuery",
    "WebUIMemoryService",
]


MemoryService = WebUIMemoryService
