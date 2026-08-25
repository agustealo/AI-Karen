"""
AI-Karen Personalization Module.

User model and preference learning runtime.
"""

from .persistence.repository import PersonalizationRepository

try:
    from .adapters import PersonalizationRepositoryAdapter
except ImportError:
    PersonalizationRepositoryAdapter = None

__all__ = ["PersonalizationRepository", "PersonalizationRepositoryAdapter"]
