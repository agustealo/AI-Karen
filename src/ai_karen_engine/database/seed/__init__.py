"""Bootstrap seed helpers for migration-owned baseline data."""

# mypy: ignore-errors

from ai_karen_engine.database.seed.rbac_seed import seed_default_roles

__all__ = ["seed_default_roles"]
