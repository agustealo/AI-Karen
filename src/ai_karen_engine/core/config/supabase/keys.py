"""Supabase key model migration.

Prepare for Supabase's current key model.
One config owner should support:
    project_url
    publishable_key
    secret_key

Legacy aliases may be accepted temporarily with deprecation warning.
Frontend receives only public/publishable credentials.
Backend secret never enters browser bundle, logs, plugin prompt, agent context.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupabaseKeyConfig:
    project_url: str = ""
    publishable_key: str = ""
    secret_key: str = ""

    legacy_anon_key: Optional[str] = None
    legacy_service_role_key: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.project_url:
            raise ValueError("project_url is required")
        if not self.publishable_key:
            raise ValueError("publishable_key is required for frontend usage")
        if not self.secret_key:
            raise ValueError("secret_key is required for backend usage")

    @property
    def public_api_url(self) -> str:
        return self.project_url.rstrip("/") + "/rest/v1"

    @property
    def has_legacy_keys(self) -> bool:
        return bool(self.legacy_anon_key or self.legacy_service_role_key)


def load_supabase_key_config() -> SupabaseKeyConfig:
    """Load config from environment.

    Supports both new and legacy key names with deprecation warnings.
    """
    project_url = os.environ.get("SUPABASE_PROJECT_URL", os.environ.get("SUPABASE_URL", ""))
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    legacy_anon = os.environ.get("SUPABASE_ANON_KEY") if "SUPABASE_ANON_KEY" in os.environ else None
    legacy_service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") if "SUPABASE_SERVICE_ROLE_KEY" in os.environ else None

    if legacy_anon or legacy_service:
        logger.warning(
            "Legacy Supabase key environment variables detected. "
            "Migrate to SUPABASE_PUBLISHABLE_KEY and SUPABASE_SECRET_KEY."
        )

    return SupabaseKeyConfig(
        project_url=project_url,
        publishable_key=publishable_key,
        secret_key=secret_key,
        legacy_anon_key=legacy_anon,
        legacy_service_role_key=legacy_service,
    )
