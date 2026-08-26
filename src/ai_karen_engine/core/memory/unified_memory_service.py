"""Deprecated compatibility surface for unified memory persistence.

Concrete storage behavior now lives under ``integrations.memory``. Cognitive
memory policy, contracts, retrieval strategy, and writeback coordination remain
under ``core.memory``. This module exists only to preserve legacy imports while
composition migrates to explicit memory ports.
"""

from ai_karen_engine.integrations.memory.unified_memory_service import *  # noqa: F401,F403
