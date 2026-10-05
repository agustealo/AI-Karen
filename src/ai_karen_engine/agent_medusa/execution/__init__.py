"""Canonical Medusa execution primitives.

Concrete execution authority lives in the run manager and coordinator. This
package intentionally exposes no generic action engine or secondary policy
manager.
"""

from .run_manager import MedusaRunManager, get_medusa_run_manager

__all__ = ["MedusaRunManager", "get_medusa_run_manager"]
