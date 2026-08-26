"""SQLAlchemy-backed profile persistence integration.

Profile synthesis semantics remain in ``core.memory.profile_synthesis``. This
module owns the concrete PostgreSQL/SQLAlchemy access required by the legacy
profile service while the composition path converges on explicit ports.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.ledger_models import ProfileFact
from ai_karen_engine.core.memory.profile_synthesis.profile_models import (
    CommunicationStyle,
    ProfileGrowth,
    ProfileSummary,
)
from ai_karen_engine.core.runtime.resilience import get_safe_stage_runner

logger = get_logger(__name__)


class ProfileService:
    """SQLAlchemy-backed profile synthesis persistence adapter."""

    def __init__(self, db_session_factory=None):
        self._db_session_factory = db_session_factory
        self.safe_runner = get_safe_stage_runner()

    def set_db_session_factory(self, factory):
        self._db_session_factory = factory

    async def get_profile_summary(self, user_id: str, tenant_id: str) -> ProfileSummary:
        user_uuid = uuid.UUID(user_id)
        tenant_uuid = uuid.UUID(tenant_id)

        if self._db_session_factory is None:
            raise RuntimeError("Profile persistence session factory is not configured")

        async with self._db_session_factory() as session:
            stmt = select(ProfileFact).where(
                ProfileFact.user_id == user_uuid,
                ProfileFact.tenant_id == tenant_uuid,
                ProfileFact.valid_to.is_(None),
            )
            result = await session.execute(stmt)
            facts = result.scalars().all()

            summary = ProfileSummary(
                user_id=user_uuid,
                tenant_id=tenant_uuid,
                name="User",
                stable_facts_count=len(facts),
            )

            categories = {}
            for fact in facts:
                categories.setdefault(fact.category, []).append(fact)

            if "communication_style" in categories:
                summary.communication_style = await self._synthesize_style(
                    categories["communication_style"]
                )
            if "preference" in categories:
                summary.top_preferences = {
                    fact.attribute: fact.value
                    for fact in categories["preference"][:10]
                }
            return summary

    async def _synthesize_style(self, facts: list[ProfileFact]) -> CommunicationStyle:
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
        user_uuid = uuid.UUID(user_id)
        if self._db_session_factory is None:
            raise RuntimeError("Profile persistence session factory is not configured")

        async with self._db_session_factory() as session:
            stmt = select(func.count(ProfileFact.fact_id)).where(
                ProfileFact.user_id == user_uuid
            )
            result = await session.execute(stmt)
            now = datetime.utcnow()
            return ProfileGrowth(
                user_id=user_uuid,
                facts_discovered=result.scalar(),
                first_seen=now,
                last_interaction=now,
            )

    async def update_profile_fact(
        self,
        user_id: str,
        tenant_id: str,
        category: str,
        attribute: str,
        value: Any,
    ) -> bool:
        user_uuid = uuid.UUID(user_id)
        tenant_uuid = uuid.UUID(tenant_id)
        if self._db_session_factory is None:
            raise RuntimeError("Profile persistence session factory is not configured")

        async with self._db_session_factory() as session:
            stmt = select(ProfileFact).where(
                ProfileFact.user_id == user_uuid,
                ProfileFact.tenant_id == tenant_uuid,
                ProfileFact.category == category,
                ProfileFact.attribute == attribute,
                ProfileFact.valid_to.is_(None),
            )
            result = await session.execute(stmt)
            existing = result.scalars().first()

            now = datetime.utcnow()
            if existing:
                existing.valid_to = now
                session.add(existing)

            fact = ProfileFact(
                event_id=uuid.uuid4(),
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                category=category,
                attribute=attribute,
                value=value,
                confidence=1.0,
                source_type="user_ui_update",
                valid_from=now,
            )
            session.add(fact)
            await session.commit()
            return True


profile_service = ProfileService()


def get_profile_service() -> ProfileService:
    return profile_service
