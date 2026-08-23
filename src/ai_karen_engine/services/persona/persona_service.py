"""
Persona Service
Business logic for managing personas, style controls, and NLP-driven adaptation.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.core.persona.contracts import (
    SYSTEM_PERSONAS,
    ChatStyleContext,
    Persona,
    PersonaMemoryEntry,
    PersonaStyleOverride,
    ToneEnum,
    UserPersonaPreferences,
    VerbosityEnum,
)

logger = logging.getLogger(__name__)


class PersonaService:
    """Service for managing personas and style controls."""

    def __init__(self, db_client: Optional[MultiTenantPostgresClient] = None, nlp_analyzer=None):
        self.db_client = db_client or MultiTenantPostgresClient()
        self.nlp_analyzer = nlp_analyzer or self._create_default_nlp_analyzer()

        self._persona_cache: Dict[str, Persona] = {}
        self._user_preferences_cache: Dict[str, UserPersonaPreferences] = {}

        for persona in SYSTEM_PERSONAS:
            self._persona_cache[persona.id] = persona

    def _create_default_nlp_analyzer(self):
        """Create a default NLP analyzer for style detection."""
        try:
            from ai_karen_engine.services.formatting.nlp_style_analyzer import NLPStyleAnalyzer

            return NLPStyleAnalyzer()
        except ImportError:
            logger.warning("NLP style analyzer not available, using mock analyzer")
            return MockNLPAnalyzer()

    @staticmethod
    def _cache_key(user_id: str, tenant_id: str) -> str:
        return f"{user_id}:{tenant_id}"

    @staticmethod
    def _normalize_tenant_id(tenant_id: Optional[str]) -> str:
        normalized = str(tenant_id or "default").strip()
        return normalized or "default"

    @staticmethod
    def _persona_payload(persona: Persona) -> Dict[str, Any]:
        return {
            "id": persona.id,
            "name": persona.name,
            "description": persona.description,
            "system_prompt": persona.system_prompt,
            "default_tone": persona.default_tone.value,
            "default_verbosity": persona.default_verbosity.value,
            "default_language": persona.default_language.value,
            "memory_weight": persona.memory_weight.value,
            "context_window_size": persona.context_window_size,
            "domain_knowledge": json.dumps(persona.domain_knowledge),
            "specialized_instructions": persona.specialized_instructions,
            "use_emoji": persona.use_emoji,
            "formality_level": persona.formality_level,
            "creativity_level": persona.creativity_level,
            "is_active": persona.is_active,
            "created_at": persona.created_at,
            "updated_at": persona.updated_at,
        }

    @staticmethod
    def _persona_embedding_text(persona: Persona) -> str:
        domain_text = " ".join(persona.domain_knowledge)
        return " ".join(
            part
            for part in [
                persona.name,
                persona.description or "",
                persona.system_prompt,
                persona.specialized_instructions or "",
                domain_text,
            ]
            if part
        )

    @staticmethod
    def _persona_embedding_metadata(persona: Persona, tenant_id: str, persona_type: str) -> Dict[str, Any]:
        return {
            "persona_id": persona.id,
            "persona_name": persona.name,
            "tenant_id": tenant_id,
            "persona_type": persona_type,
            "default_tone": persona.default_tone.value,
            "default_verbosity": persona.default_verbosity.value,
            "default_language": persona.default_language.value,
            "domain_knowledge": persona.domain_knowledge,
            "specialized_instructions": persona.specialized_instructions,
            "use_emoji": persona.use_emoji,
            "formality_level": persona.formality_level,
            "creativity_level": persona.creativity_level,
            "is_system_persona": persona.is_system_persona,
        }

    @staticmethod
    def _persona_from_row(row: Any) -> Persona:
        domain_knowledge = row.domain_knowledge
        if isinstance(domain_knowledge, str):
            try:
                domain_knowledge = json.loads(domain_knowledge)
            except json.JSONDecodeError:
                domain_knowledge = []
        return Persona(
            id=row.id,
            name=row.name,
            description=row.description,
            system_prompt=row.system_prompt,
            default_tone=row.default_tone,
            default_verbosity=row.default_verbosity,
            default_language=row.default_language,
            memory_weight=row.memory_weight,
            context_window_size=row.context_window_size,
            domain_knowledge=domain_knowledge or [],
            specialized_instructions=row.specialized_instructions,
            use_emoji=row.use_emoji,
            formality_level=row.formality_level,
            creativity_level=row.creativity_level,
            created_at=row.created_at,
            updated_at=row.updated_at,
            is_active=row.is_active,
            is_system_persona=False,
        )

    @staticmethod
    def _preferences_from_row(
        row: Any,
        *,
        user_id: str,
        tenant_id: str,
    ) -> UserPersonaPreferences:
        if row is None:
            return UserPersonaPreferences(user_id=user_id, tenant_id=tenant_id)
        return UserPersonaPreferences(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            active_persona_id=row.active_persona_id,
            default_tone=row.default_tone,
            default_verbosity=row.default_verbosity,
            default_language=row.default_language,
            enable_style_adaptation=row.enable_style_adaptation,
            adaptation_sensitivity=row.adaptation_sensitivity,
            enable_persona_memory_filtering=row.enable_persona_memory_filtering,
            cross_persona_memory_sharing=row.cross_persona_memory_sharing,
            show_persona_selector=row.show_persona_selector,
            show_style_controls=row.show_style_controls,
            enable_quick_style_adjustments=row.enable_quick_style_adjustments,
            updated_at=row.updated_at,
        )

    async def _load_custom_personas(self, user_id: str, tenant_id: str) -> List[Persona]:
        query = text(
            """
            SELECT
                id,
                name,
                description,
                system_prompt,
                default_tone,
                default_verbosity,
                default_language,
                memory_weight,
                context_window_size,
                domain_knowledge,
                specialized_instructions,
                use_emoji,
                formality_level,
                creativity_level,
                created_at,
                updated_at,
                is_active
            FROM custom_personas
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            ORDER BY created_at ASC
            """
        )
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                query,
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            rows = result.fetchall()
        personas = [self._persona_from_row(row) for row in rows]
        for persona in personas:
            self._persona_cache[persona.id] = persona
        return personas

    async def _insert_persona(self, user_id: str, tenant_id: str, persona: Persona) -> None:
        query = text(
            """
            INSERT INTO custom_personas (
                id,
                tenant_id,
                user_id,
                name,
                description,
                system_prompt,
                default_tone,
                default_verbosity,
                default_language,
                memory_weight,
                context_window_size,
                domain_knowledge,
                specialized_instructions,
                use_emoji,
                formality_level,
                creativity_level,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :tenant_id,
                :user_id,
                :name,
                :description,
                :system_prompt,
                :default_tone,
                :default_verbosity,
                :default_language,
                :memory_weight,
                :context_window_size,
                :domain_knowledge,
                :specialized_instructions,
                :use_emoji,
                :formality_level,
                :creativity_level,
                :is_active,
                :created_at,
                :updated_at
            )
            """
        )
        payload = self._persona_payload(persona)
        payload["tenant_id"] = tenant_id
        payload["user_id"] = user_id
        async with self.db_client.get_async_session() as session:
            await session.execute(query, payload)

    async def _update_persona_record(self, user_id: str, tenant_id: str, persona: Persona) -> None:
        query = text(
            """
            UPDATE custom_personas
            SET
                name = :name,
                description = :description,
                system_prompt = :system_prompt,
                default_tone = :default_tone,
                default_verbosity = :default_verbosity,
                default_language = :default_language,
                memory_weight = :memory_weight,
                context_window_size = :context_window_size,
                domain_knowledge = :domain_knowledge,
                specialized_instructions = :specialized_instructions,
                use_emoji = :use_emoji,
                formality_level = :formality_level,
                creativity_level = :creativity_level,
                is_active = :is_active,
                updated_at = :updated_at
            WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id
            """
        )
        payload = self._persona_payload(persona)
        payload["tenant_id"] = tenant_id
        payload["user_id"] = user_id
        async with self.db_client.get_async_session() as session:
            await session.execute(query, payload)

    async def _delete_persona_record(self, user_id: str, tenant_id: str, persona_id: str) -> int:
        async with self.db_client.get_async_session() as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM custom_personas
                    WHERE id = :persona_id AND tenant_id = :tenant_id AND user_id = :user_id
                    """
                ),
                {
                    "persona_id": persona_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
        return int(result.rowcount or 0)

    async def create_persona(
        self,
        user_id: str,
        tenant_id: str,
        persona_data: Dict[str, Any],
    ) -> Persona:
        """Create a new custom persona for a user."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        persona = Persona(**persona_data)
        persona.is_system_persona = False

        preferences = await self.get_user_preferences(user_id, tenant_id)
        existing_names = {p.name.lower() for p in preferences.custom_personas}
        if persona.name.lower() in existing_names:
            raise ValueError(f"Persona name '{persona.name}' already exists")

        await self._insert_persona(user_id, tenant_id, persona)
        preferences.custom_personas.append(persona)
        preferences.updated_at = datetime.utcnow()
        await self._save_user_preferences(user_id, tenant_id, preferences)

        self._persona_cache[persona.id] = persona
        self._user_preferences_cache[self._cache_key(user_id, tenant_id)] = preferences
        logger.info("Created persona '%s' for user %s", persona.name, user_id)
        return persona

    async def update_persona(
        self,
        user_id: str,
        tenant_id: str,
        persona_id: str,
        updates: Dict[str, Any],
    ) -> Persona:
        """Update an existing persona."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        if persona_id in {p.id for p in SYSTEM_PERSONAS}:
            raise ValueError("System personas cannot be modified")

        preferences = await self.get_user_preferences(user_id, tenant_id)
        persona_index = next(
            (index for index, persona in enumerate(preferences.custom_personas) if persona.id == persona_id),
            None,
        )
        if persona_index is None:
            raise ValueError(f"Persona {persona_id} not found")

        candidate_name = str(updates.get("name", preferences.custom_personas[persona_index].name)).strip().lower()
        for existing in preferences.custom_personas:
            if existing.id != persona_id and existing.name.lower() == candidate_name:
                raise ValueError(f"Persona name '{updates.get('name')}' already exists")

        persona_dict = preferences.custom_personas[persona_index].dict()
        persona_dict.update(updates)
        persona_dict["updated_at"] = datetime.utcnow()
        updated_persona = Persona(**persona_dict)

        await self._update_persona_record(user_id, tenant_id, updated_persona)
        preferences.custom_personas[persona_index] = updated_persona
        preferences.updated_at = datetime.utcnow()
        await self._save_user_preferences(user_id, tenant_id, preferences)

        self._persona_cache[persona_id] = updated_persona
        self._user_preferences_cache[self._cache_key(user_id, tenant_id)] = preferences
        logger.info("Updated persona '%s' for user %s", updated_persona.name, user_id)
        return updated_persona

    async def delete_persona(self, user_id: str, tenant_id: str, persona_id: str) -> bool:
        """Delete a custom persona."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        if persona_id in {p.id for p in SYSTEM_PERSONAS}:
            raise ValueError("System personas cannot be deleted")

        preferences = await self.get_user_preferences(user_id, tenant_id)
        deleted = await self._delete_persona_record(user_id, tenant_id, persona_id)
        if deleted == 0:
            return False

        preferences.custom_personas = [
            persona for persona in preferences.custom_personas if persona.id != persona_id
        ]
        if preferences.active_persona_id == persona_id:
            preferences.active_persona_id = None
        preferences.updated_at = datetime.utcnow()
        await self._save_user_preferences(user_id, tenant_id, preferences)

        self._persona_cache.pop(persona_id, None)
        self._user_preferences_cache[self._cache_key(user_id, tenant_id)] = preferences
        logger.info("Deleted persona %s for user %s", persona_id, user_id)
        return True

    async def get_persona(
        self,
        persona_id: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[Persona]:
        """Get a persona by ID."""
        if persona_id in self._persona_cache:
            return self._persona_cache[persona_id]

        for persona in SYSTEM_PERSONAS:
            if persona.id == persona_id:
                self._persona_cache[persona_id] = persona
                return persona

        if user_id and tenant_id:
            preferences = await self.get_user_preferences(user_id, tenant_id)
            for persona in preferences.custom_personas:
                if persona.id == persona_id:
                    self._persona_cache[persona_id] = persona
                    return persona
        return None

    async def list_available_personas(self, user_id: str, tenant_id: str) -> List[Persona]:
        """List all personas available to a user (system + custom)."""
        preferences = await self.get_user_preferences(user_id, self._normalize_tenant_id(tenant_id))
        personas = list(SYSTEM_PERSONAS)
        personas.extend(preferences.custom_personas)
        return [persona for persona in personas if persona.is_active]

    async def get_user_preferences(self, user_id: str, tenant_id: str) -> UserPersonaPreferences:
        """Get user's persona preferences."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        cache_key = self._cache_key(user_id, tenant_id)
        if cache_key in self._user_preferences_cache:
            return self._user_preferences_cache[cache_key]

        preferences_data = await self._load_user_preferences(user_id, tenant_id)
        if preferences_data:
            preferences = UserPersonaPreferences(**preferences_data)
        else:
            preferences = UserPersonaPreferences(user_id=user_id, tenant_id=tenant_id)
            await self._save_user_preferences(user_id, tenant_id, preferences)

        preferences.custom_personas = await self._load_custom_personas(user_id, tenant_id)
        self._user_preferences_cache[cache_key] = preferences
        return preferences

    async def update_user_preferences(
        self,
        user_id: str,
        tenant_id: str,
        updates: Dict[str, Any],
    ) -> UserPersonaPreferences:
        """Update user's persona preferences."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        preferences = await self.get_user_preferences(user_id, tenant_id)
        previous_active_persona_id = preferences.active_persona_id

        for key, value in updates.items():
            if hasattr(preferences, key):
                setattr(preferences, key, value)

        if preferences.active_persona_id:
            active_persona = await self.get_persona(preferences.active_persona_id, user_id, tenant_id)
            if active_persona is None:
                raise ValueError(f"Persona {preferences.active_persona_id} not found")

        preferences.updated_at = datetime.utcnow()
        await self._save_user_preferences(user_id, tenant_id, preferences)
        self._user_preferences_cache[self._cache_key(user_id, tenant_id)] = preferences
        logger.info("Updated preferences for user %s", user_id)
        return preferences

    async def switch_persona(
        self,
        user_id: str,
        tenant_id: str,
        persona_id: Optional[str],
    ) -> UserPersonaPreferences:
        """Switch user's active persona."""
        persona = None
        if persona_id:
            persona = await self.get_persona(persona_id, user_id, tenant_id)
            if not persona:
                raise ValueError(f"Persona {persona_id} not found")
        return await self.update_user_preferences(
            user_id,
            tenant_id,
            {"active_persona_id": persona_id},
        )

    async def analyze_user_style(self, message: str) -> Dict[str, Any]:
        """Analyze user's writing style using NLP."""
        try:
            analysis = await self.nlp_analyzer.analyze_style(message)
            return {
                "detected_tone": analysis.get("tone"),
                "formality_score": analysis.get("formality", 0.5),
                "sentiment_score": analysis.get("sentiment", 0.0),
                "complexity_score": analysis.get("complexity", 0.5),
                "emotion_indicators": analysis.get("emotions", []),
            }
        except Exception as exc:
            logger.warning("Style analysis failed: %s", exc)
            return {
                "detected_tone": None,
                "formality_score": 0.5,
                "sentiment_score": 0.0,
                "complexity_score": 0.5,
                "emotion_indicators": [],
            }

    async def build_chat_context(
        self,
        user_id: str,
        tenant_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        style_override: Optional[PersonaStyleOverride] = None,
        turn_number: int = 1,
    ) -> ChatStyleContext:
        """Build complete chat style context for a conversation turn."""
        tenant_id = self._normalize_tenant_id(tenant_id)
        preferences = await self.get_user_preferences(user_id, tenant_id)

        persona = None
        if preferences.active_persona_id:
            persona = await self.get_persona(preferences.active_persona_id, user_id, tenant_id)

        style_analysis = {}
        if preferences.enable_style_adaptation:
            style_analysis = await self.analyze_user_style(message)

        context = ChatStyleContext(
            persona=persona,
            style_override=style_override,
            detected_user_tone=style_analysis.get("detected_tone"),
            detected_formality=style_analysis.get("formality_score"),
            detected_sentiment=style_analysis.get("sentiment_score"),
            conversation_id=conversation_id,
            turn_number=turn_number,
        )
        if preferences.enable_persona_memory_filtering and persona:
            context.memory_persona_filter = persona.id
            context.memory_tone_filter = persona.default_tone
        return context

    async def store_persona_memory(
        self,
        user_id: str,
        tenant_id: str,
        content: str,
        context: ChatStyleContext,
        conversation_id: Optional[str] = None,
        importance_score: float = 0.5,
    ) -> PersonaMemoryEntry:
        """Store a memory entry with persona context."""
        memory_entry = PersonaMemoryEntry(
            content=content,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            importance_score=importance_score,
        )
        if context.persona:
            memory_entry.persona_id = context.persona.id
            memory_entry.persona_name = context.persona.name
            memory_entry.tone_used = context.get_effective_tone()
            memory_entry.verbosity_used = context.get_effective_verbosity()
        await self._store_memory_entry(memory_entry)
        logger.debug("Stored persona memory for user %s", user_id)
        return memory_entry

    async def recall_persona_memories(
        self,
        user_id: str,
        tenant_id: str,
        query: str,
        context: ChatStyleContext,
        limit: int = 10,
    ) -> List[PersonaMemoryEntry]:
        """Recall memories with persona-aware filtering."""
        filters = {"user_id": user_id, "tenant_id": tenant_id}
        if context.memory_persona_filter:
            filters["persona_id"] = context.memory_persona_filter
        if context.memory_tone_filter:
            filters["tone_used"] = context.memory_tone_filter.value
        memories = await self._retrieve_memories(query, filters, limit)
        logger.debug("Retrieved %d persona memories for user %s", len(memories), user_id)
        return memories

    async def _load_user_preferences(self, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Load user preferences from database."""
        if not self.db_client:
            return None
        try:
            query = text(
                """
                SELECT
                    tenant_id,
                    user_id,
                    active_persona_id,
                    default_tone,
                    default_verbosity,
                    default_language,
                    enable_style_adaptation,
                    adaptation_sensitivity,
                    enable_persona_memory_filtering,
                    cross_persona_memory_sharing,
                    show_persona_selector,
                    show_style_controls,
                    enable_quick_style_adjustments,
                    updated_at
                FROM user_persona_preferences
                WHERE tenant_id = :tenant_id AND user_id = :user_id
                """
            )
            async with self.db_client.get_async_session() as session:
                result = await session.execute(
                    query,
                    {"tenant_id": tenant_id, "user_id": user_id},
                )
                row = result.fetchone()
            if row is None:
                return None
            preferences = self._preferences_from_row(row, user_id=user_id, tenant_id=tenant_id)
            return preferences.dict(exclude={"custom_personas"})
        except Exception as exc:
            logger.error("Failed to load user preferences: %s", exc)
            return None

    async def _save_user_preferences(
        self,
        user_id: str,
        tenant_id: str,
        preferences: UserPersonaPreferences,
    ) -> bool:
        """Save user preferences to database."""
        if not self.db_client:
            logger.warning("No database client available for saving preferences")
            return False
        try:
            query = text(
                """
                INSERT INTO user_persona_preferences (
                    tenant_id,
                    user_id,
                    active_persona_id,
                    default_tone,
                    default_verbosity,
                    default_language,
                    enable_style_adaptation,
                    adaptation_sensitivity,
                    enable_persona_memory_filtering,
                    cross_persona_memory_sharing,
                    show_persona_selector,
                    show_style_controls,
                    enable_quick_style_adjustments,
                    created_at,
                    updated_at
                ) VALUES (
                    :tenant_id,
                    :user_id,
                    :active_persona_id,
                    :default_tone,
                    :default_verbosity,
                    :default_language,
                    :enable_style_adaptation,
                    :adaptation_sensitivity,
                    :enable_persona_memory_filtering,
                    :cross_persona_memory_sharing,
                    :show_persona_selector,
                    :show_style_controls,
                    :enable_quick_style_adjustments,
                    :created_at,
                    :updated_at
                )
                ON CONFLICT (tenant_id, user_id)
                DO UPDATE SET
                    active_persona_id = EXCLUDED.active_persona_id,
                    default_tone = EXCLUDED.default_tone,
                    default_verbosity = EXCLUDED.default_verbosity,
                    default_language = EXCLUDED.default_language,
                    enable_style_adaptation = EXCLUDED.enable_style_adaptation,
                    adaptation_sensitivity = EXCLUDED.adaptation_sensitivity,
                    enable_persona_memory_filtering = EXCLUDED.enable_persona_memory_filtering,
                    cross_persona_memory_sharing = EXCLUDED.cross_persona_memory_sharing,
                    show_persona_selector = EXCLUDED.show_persona_selector,
                    show_style_controls = EXCLUDED.show_style_controls,
                    enable_quick_style_adjustments = EXCLUDED.enable_quick_style_adjustments,
                    updated_at = EXCLUDED.updated_at
                """
            )
            payload = {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "active_persona_id": preferences.active_persona_id,
                "default_tone": preferences.default_tone.value,
                "default_verbosity": preferences.default_verbosity.value,
                "default_language": preferences.default_language.value,
                "enable_style_adaptation": preferences.enable_style_adaptation,
                "adaptation_sensitivity": preferences.adaptation_sensitivity,
                "enable_persona_memory_filtering": preferences.enable_persona_memory_filtering,
                "cross_persona_memory_sharing": preferences.cross_persona_memory_sharing,
                "show_persona_selector": preferences.show_persona_selector,
                "show_style_controls": preferences.show_style_controls,
                "enable_quick_style_adjustments": preferences.enable_quick_style_adjustments,
                "created_at": preferences.updated_at,
                "updated_at": preferences.updated_at,
            }
            async with self.db_client.get_async_session() as session:
                await session.execute(query, payload)
            return True
        except Exception as exc:
            logger.error("Failed to save user preferences: %s", exc)
            return False

    async def _store_memory_entry(self, memory_entry: PersonaMemoryEntry) -> bool:
        """Store memory entry in database."""
        if not self.db_client:
            logger.warning("No database client available for storing memory")
            return False
        try:
            query = text(
                """
                INSERT INTO persona_memory_entries (
                    id,
                    tenant_id,
                    user_id,
                    conversation_id,
                    persona_id,
                    persona_name,
                    tone_used,
                    verbosity_used,
                    content,
                    memory_type,
                    importance_score,
                    embedding_id,
                    created_at,
                    accessed_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :user_id,
                    :conversation_id,
                    :persona_id,
                    :persona_name,
                    :tone_used,
                    :verbosity_used,
                    :content,
                    :memory_type,
                    :importance_score,
                    :embedding_id,
                    :created_at,
                    :accessed_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    conversation_id = EXCLUDED.conversation_id,
                    persona_id = EXCLUDED.persona_id,
                    persona_name = EXCLUDED.persona_name,
                    tone_used = EXCLUDED.tone_used,
                    verbosity_used = EXCLUDED.verbosity_used,
                    content = EXCLUDED.content,
                    memory_type = EXCLUDED.memory_type,
                    importance_score = EXCLUDED.importance_score,
                    embedding_id = EXCLUDED.embedding_id,
                    accessed_at = EXCLUDED.accessed_at
                """
            )
            payload = {
                "id": memory_entry.id,
                "tenant_id": memory_entry.tenant_id,
                "user_id": memory_entry.user_id,
                "conversation_id": memory_entry.conversation_id,
                "persona_id": memory_entry.persona_id,
                "persona_name": memory_entry.persona_name,
                "tone_used": memory_entry.tone_used.value if memory_entry.tone_used else None,
                "verbosity_used": memory_entry.verbosity_used.value if memory_entry.verbosity_used else None,
                "content": memory_entry.content,
                "memory_type": memory_entry.memory_type,
                "importance_score": memory_entry.importance_score,
                "embedding_id": memory_entry.embedding_id,
                "created_at": memory_entry.created_at,
                "accessed_at": memory_entry.accessed_at,
            }
            async with self.db_client.get_async_session() as session:
                await session.execute(query, payload)
            return True
        except Exception as exc:
            logger.error("Failed to store memory entry: %s", exc)
            return False

    async def _retrieve_memories(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int,
    ) -> List[PersonaMemoryEntry]:
        """Retrieve memories from database with filtering."""
        if not self.db_client:
            logger.warning("No database client available for retrieving memories")
            return []
        try:
            clauses = [
                "user_id = :user_id",
                "tenant_id = :tenant_id",
            ]
            params: Dict[str, Any] = {
                "user_id": filters.get("user_id"),
                "tenant_id": filters.get("tenant_id"),
                "limit": limit,
            }
            if filters.get("persona_id"):
                clauses.append("persona_id = :persona_id")
                params["persona_id"] = filters["persona_id"]
            if filters.get("tone_used"):
                clauses.append("tone_used = :tone_used")
                params["tone_used"] = filters["tone_used"]
            if query.strip():
                clauses.append("(content ILIKE :pattern OR COALESCE(persona_name, '') ILIKE :pattern)")
                params["pattern"] = f"%{query.strip()}%"

            sql = text(
                f"""
                SELECT
                    id,
                    tenant_id,
                    user_id,
                    conversation_id,
                    persona_id,
                    persona_name,
                    tone_used,
                    verbosity_used,
                    content,
                    memory_type,
                    importance_score,
                    embedding_id,
                    created_at,
                    accessed_at
                FROM persona_memory_entries
                WHERE {' AND '.join(clauses)}
                ORDER BY importance_score DESC, created_at DESC
                LIMIT :limit
                """
            )
            async with self.db_client.get_async_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()

            memories: List[PersonaMemoryEntry] = []
            for row in rows:
                memories.append(
                    PersonaMemoryEntry(
                        id=row.id,
                        content=row.content,
                        persona_id=row.persona_id,
                        persona_name=row.persona_name,
                        tone_used=ToneEnum(row.tone_used) if row.tone_used else None,
                        verbosity_used=VerbosityEnum(row.verbosity_used) if row.verbosity_used else None,
                        user_id=row.user_id,
                        tenant_id=row.tenant_id,
                        conversation_id=row.conversation_id,
                        memory_type=row.memory_type,
                        importance_score=row.importance_score,
                        created_at=row.created_at,
                        accessed_at=row.accessed_at,
                        embedding_id=row.embedding_id,
                    )
                )
            return memories
        except Exception as exc:
            logger.error("Failed to retrieve memories: %s", exc)
            return []


class MockNLPAnalyzer:
    """Mock NLP analyzer for when spaCy/transformers are not available."""

    async def analyze_style(self, text: str) -> Dict[str, Any]:
        """Mock style analysis."""
        word_count = len(text.split())
        has_questions = "?" in text
        has_exclamations = "!" in text
        formal_words = ["please", "thank you", "kindly", "regards"]
        casual_words = ["hey", "yeah", "cool", "awesome", "lol"]

        formality_score = 0.5
        if any(word in text.lower() for word in formal_words):
            formality_score += 0.2
        if any(word in text.lower() for word in casual_words):
            formality_score -= 0.2
        formality_score = max(0.0, min(1.0, formality_score))

        tone = ToneEnum.FRIENDLY
        if formality_score > 0.7:
            tone = ToneEnum.PROFESSIONAL
        elif formality_score < 0.3:
            tone = ToneEnum.CASUAL
        elif has_questions and word_count > 20:
            tone = ToneEnum.TECHNICAL

        return {
            "tone": tone,
            "formality": formality_score,
            "sentiment": 0.1 if has_exclamations else -0.1 if "problem" in text.lower() else 0.0,
            "complexity": min(1.0, word_count / 50.0),
            "emotions": ["curious"] if has_questions else ["neutral"],
        }


_persona_service: Optional[PersonaService] = None


def get_persona_service(db_client: Optional[MultiTenantPostgresClient] = None) -> PersonaService:
    """Get the global persona service instance."""
    global _persona_service
    if _persona_service is None:
        _persona_service = PersonaService(db_client=db_client)
    elif db_client is not None and _persona_service.db_client is not db_client:
        _persona_service = PersonaService(db_client=db_client, nlp_analyzer=_persona_service.nlp_analyzer)
    return _persona_service


def initialize_persona_service(db_client=None, nlp_analyzer=None) -> PersonaService:
    """Initialize the global persona service with dependencies."""
    global _persona_service
    _persona_service = PersonaService(db_client=db_client, nlp_analyzer=nlp_analyzer)
    return _persona_service
