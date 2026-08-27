"""Deprecated compatibility surface for the legacy SQL-backed memory runtime.

Concrete database persistence has moved outside cognitive Core. New code should
compose memory through ``core.memory`` ports/runtime APIs rather than importing
this implementation directly.
"""

from ai_karen_engine.integrations.memory.legacy_memory_runtime_impl import *  # noqa: F401,F403
