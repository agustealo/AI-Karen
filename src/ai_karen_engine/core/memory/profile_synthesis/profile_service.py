"""Deprecated compatibility surface for profile persistence.

Cognitive profile contracts and synthesis semantics remain under ``core.memory``.
Concrete SQLAlchemy persistence lives under ``integrations.memory`` and is
re-exported here only while legacy imports are migrated.
"""

from ai_karen_engine.integrations.memory.profile_service import (
    ProfileService,
    get_profile_service,
    profile_service,
)

__all__ = ["ProfileService", "get_profile_service", "profile_service"]
