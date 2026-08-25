"""
Profile Service for AI Karen Memory System.

The central authority for profile management and synthesis.
Consumes durable memory facts and publishes a compact ProfileSummary.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from ai_karen_engine.core.logging import get_logger

from ...runtime.resilience import get_safe_stage_runner
from ..ledger_models import ProfileFact
from .profile_models import CommunicationStyle, ProfileGrowth, ProfileSummary

logger = get_logger(__name__)

class ProfileService:
    """Service for synthesizing and managing user/org profiles."""

    def __init__(self, db_session_factory=None):
        self._db_session_factory = db_session_factory
        self.safe_runner = get_safe_stage_runner()

    def set_db_session_factory(self, factory):
        self._db_session_factory = factory

    async def get_profile_summary(self, user_id: str, tenant_id: str) -> ProfileSummary:
        """
        Synthesize a compact profile summary for runtime consumption.
        """
        user_uuid = uuid.UUID(user_id)
        tenant_uuid = uuid.UUID(tenant_id)
        
        async with self._db_session_factory() as session:
            # 1. Fetch stable facts
            stmt = select(ProfileFact).where(
                ProfileFact.user_id == user_uuid,
                ProfileFact.tenant_id == tenant_uuid,
                ProfileFact.valid_to.is_(None)
            )
            result = await session.execute(stmt)
            facts = result.scalars().all()
            
            # 2. Synthesize components (with resilience)
            summary = ProfileSummary(
                user_id=user_uuid,
                tenant_id=tenant_uuid,
                name="User", # Should be fetched from AuthUser if possible
                stable_facts_count=len(facts)
            )
            
            # Group facts by category
            categories = {}
            for fact in facts:
                if fact.category not in categories:
                    categories[fact.category] = []
                categories[fact.category].append(fact)
            
            # Synthesize Communication Style
            if "communication_style" in categories:
                # Logic to resolve best-fit style
                summary.communication_style = await self._synthesize_style(categories["communication_style"])
            
            # Top Preferences
            if "preference" in categories:
                summary.top_preferences = {f.attribute: f.value for f in categories["preference"][:10]}
            
            return summary

    async def _synthesize_style(self, facts: list[ProfileFact]) -> CommunicationStyle:
        """Resolve conflicting style facts into a single model."""
        # Simple majority or most recent logic for now
        style = CommunicationStyle()
        for fact in facts:
            val = fact.value
            if isinstance(val, dict):
                if "tone" in val:
                    style.tone = val["tone"]
                if "verbosity" in val:
                    style.verbosity = val["verbosity"]
        return style

    async def track_growth(self, user_id: str) -> ProfileGrowth:
        """Calculate growth metrics for a user profile."""
        user_uuid = uuid.UUID(user_id)
        async with self._db_session_factory() as session:
            # Count facts
            fact_count_stmt = select(func.count(ProfileFact.fact_id)).where(ProfileFact.user_id == user_uuid)
            fact_count_result = await session.execute(fact_count_stmt)
            
            return ProfileGrowth(
                user_id=user_uuid,
                facts_discovered=fact_count_result.scalar(),
                first_seen=datetime.utcnow(), # Placeholder
                last_interaction=datetime.utcnow()
            )

    async def update_profile_fact(
        self, user_id: str, tenant_id: str, category: str, attribute: str, value: Any
    ) -> bool:
        """Update or create a profile fact directly."""
        user_uuid = uuid.UUID(user_id)
        tenant_uuid = uuid.UUID(tenant_id)
        
        async with self._db_session_factory() as session:
            # 1. Supersede existing fact if present
            stmt = select(ProfileFact).where(
                ProfileFact.user_id == user_uuid,
                ProfileFact.tenant_id == tenant_uuid,
                ProfileFact.category == category,
                ProfileFact.attribute == attribute,
                ProfileFact.valid_to.is_(None)
            )
            result = await session.execute(stmt)
            existing = result.scalars().first()
            
            now = datetime.utcnow()
            if existing:
                existing.valid_to = now
                session.add(existing)

            # 2. Create new fact (headless event for manual updates)
            # In a full ledger-first model, this would be a MemoryEvent first
            fact = ProfileFact(
                event_id=uuid.uuid4(), # head-less event for direct UI updates
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                category=category,
                attribute=attribute,
                value=value,
                confidence=1.0,
                source_type="user_ui_update",
                valid_from=now
            )
            session.add(fact)
            await session.commit()
            return True

# Global instance
profile_service = ProfileService()

def get_profile_service() -> ProfileService:
    return profile_service
