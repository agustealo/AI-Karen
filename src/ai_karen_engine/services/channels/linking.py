"""Governed channel identity proof issuance.

Only a fresh authenticated Karen principal and a session-bound RuntimePolicy
plan may mint one expiring link challenge. Native protocol attestation and
binding are owned by ChannelIngressService + SqlChannelRepository; no
adapter, user prompt or external sender can supply a Karen user_id.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate, AuthorizedExecutionPlan,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels.activation import ChannelActivationService

logger = logging.getLogger(__name__)


class ChannelLinkDenied(PermissionError):
    """Cannot issue native identity proof for this principal/connection."""


class ChannelLinkConflict(RuntimeError):
    """The challenge could not be atomically reserved."""


@dataclass(frozen=True, slots=True, repr=False)
class IssuedChannelLink:
    """One-time secret. Never log, serialize to history or persist plaintext."""

    challenge_id: str
    command: str
    expires_in_seconds: int


class ChannelLinkService:
    """Host-owned operator of one-use identity proofs, not an AI runtime."""

    def __init__(
        self, *, kernel: PluginKernel, repository: SqlChannelRepository,
        principal_lookup: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._kernel = kernel
        self._repository = repository
        self._principal_lookup = (
            principal_lookup or ChannelActivationService._fresh_principal
        )

    async def issue_challenge(
        self, *, tenant_id: str, user_id: str, session_id: str,
        connection_id: str, authorized_plan: AuthorizedExecutionPlan,
        ttl_seconds: int = 600,
    ) -> IssuedChannelLink:
        if not 60 <= ttl_seconds <= 900:
            raise ValueError("Link proof TTL must be between 60 and 900 seconds")
        connection = await self._repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise ChannelLinkDenied("Host channel connection unavailable")
        if self._kernel.get_channel_activation_manifest(
            connection.installation_id
        ) is None:
            raise ChannelLinkDenied("Installed channel is not available")
        principal = await self._principal_lookup(
            tenant_id=tenant_id, user_id=user_id,
        )
        if (
            principal is None
            or getattr(principal, "status", None) is not UserStatus.ACTIVE
            or str(getattr(principal, "tenant_id", "")) != tenant_id
            or str(getattr(principal, "id", "")) != user_id
            or getattr(principal, "is_verified", False) is not True
        ):
            raise ChannelLinkDenied("Active verified Karen account required")
        action = "channel.link"
        if (
            not isinstance(authorized_plan, AuthorizedExecutionPlan)
            or not authorized_plan.matches_execution_scope(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            )
            or connection.installation_id not in authorized_plan.allowed_plugins
            or action not in authorized_plan.allowed_capabilities
            or authorized_plan.approval_requirements
            or not await ActionExecutionGate.authorize(authorized_plan, action)
        ):
            raise ChannelLinkDenied("RuntimePolicy did not authorize identity linking")

        # secrets.token_urlsafe(32) encodes 256 random bits in 43 ASCII chars.
        # The challenge SQL stores a SHA-256 digest, never the raw code.
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        challenge_id = await self._repository.issue_link_challenge(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, proof_digest=digest, ttl_seconds=ttl_seconds,
        )
        if challenge_id is None:
            raise ChannelLinkConflict("Channel identity proof could not be issued")
        logger.info(
            "channel.identity.challenge_issued",
            extra={
                "tenant_id": tenant_id, "user_id": user_id,
                "connection_id": connection_id,
                "challenge_id": challenge_id,
                "policy_decision_id": authorized_plan.policy_decision_id,
            },
        )
        return IssuedChannelLink(
            challenge_id=challenge_id,
            command=f"/link {token}",
            expires_in_seconds=ttl_seconds,
        )


__all__ = [
    "ChannelLinkConflict",
    "ChannelLinkDenied",
    "ChannelLinkService",
    "IssuedChannelLink",
]
