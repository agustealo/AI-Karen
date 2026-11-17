"""One host lifecycle owner for installed, audited channel transport dependencies.

The FastAPI lifespan owns this service. The PluginKernel remains catalog
authority; CredentialVaultService remains secret and audit authority;
SqlChannelRepository remains tenant/identity/persistence authority. This host
merely wires those existing owners into installed native transport adapters.

Do not auto-start tenant connections from a persisted 'enabled' bit. After a
process restart, native transports remain inactive until explicitly resumed
through a future governed reconciliation process. Authenticated ingress may
schedule its committed inbox receipt immediately; persisted backlog discovery
requires a separate tenant-authorized reconciliation action.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import httpx

from ai_karen_engine.config.channels import ChannelHostSettings
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
from ai_karen_engine.services.channels.activation import ChannelActivationConflict, ChannelActivationService
from ai_karen_engine.services.channels.credentials import ChannelVaultSecretResolver
from ai_karen_engine.services.channels.ingress import ChannelIngressService
from ai_karen_engine.services.channels.linking import ChannelLinkService, IssuedChannelLink
from ai_karen_engine.services.channels.execution import ChannelExecutionService
from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
from ai_karen_engine.services.channels.worker import ChannelInboxWorker
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
)

logger = logging.getLogger(__name__)


class ChannelHostServices:
    """Private process owner of exactly one canonical channel host dependency set."""

    def __init__(
        self, *,
        settings: ChannelHostSettings,
        kernel: PluginKernel,
        repository: SqlChannelRepository,
        vault: CredentialVaultService,
        http_client: httpx.AsyncClient,
        owns_vault: bool = True,
        owns_kernel: bool = True,
        chat_runtime: object | None = None,
    ) -> None:
        self.settings = settings.validate()
        if not self.settings.enabled:
            raise ValueError("Disabled channel host must not instantiate transports")
        self.kernel = kernel
        self.repository = repository
        self.vault = vault
        self.http_client = http_client
        self._owns_vault = owns_vault
        self._owns_kernel = owns_kernel
        self._chat_runtime = chat_runtime
        self.ingress: ChannelIngressService | None = None
        self.activation: ChannelActivationService | None = None
        self.linking: ChannelLinkService | None = None
        self.execution: ChannelExecutionService | None = None
        self.delivery: ChannelDeliveryService | None = None
        self.worker: ChannelInboxWorker | None = None
        self._installed: dict[str, object] = {}
        self._resolvers: dict[str, ChannelVaultSecretResolver] = {}
        self._initialized = False
        self._closed = False

    async def initialize(self) -> None:
        """Bind only configured, catalog-verified adapters; no tenant activation."""
        if self._closed:
            raise RuntimeError("Closed channel host cannot be restarted")
        if self._initialized:
            return
        try:
            await self.kernel.initialize()
            await self.vault.initialize()
            for installation_id, secret_types in self.settings.installations.items():
                if self.kernel.get_channel_activation_manifest(installation_id) is None:
                    raise RuntimeError("Configured communication installation is unavailable")
                adapter = self.kernel.loader.load_extension(installation_id)
                if not self.kernel.is_canonical_channel_adapter(installation_id, adapter):
                    raise RuntimeError("Transport is not the canonical installed adapter")
                if not callable(getattr(adapter, "bind_host_services", None)):
                    raise RuntimeError("Installed channel cannot accept host services")
                resolver = ChannelVaultSecretResolver(
                    vault=self.vault, installation_id=installation_id,
                    required_secret_types=secret_types,
                    service_principal_id=self.settings.service_principal_id,
                )
                # A transport is deliberately not started here. Only
                # ChannelActivationService with an authorized action may do so.
                adapter.bind_host_services(
                    secret_resolver=resolver, http_client=self.http_client,
                )
                self._installed[installation_id] = adapter
                self._resolvers[installation_id] = resolver
                await adapter.initialize()

            self.activation = ChannelActivationService(
                kernel=self.kernel, repository=self.repository,
                credential_authorizer=self.authorize_reference,
            )
            self.linking = ChannelLinkService(
                kernel=self.kernel, repository=self.repository,
            )
            # A worker is permitted only after the canonical ChatRuntime has
            # been attached. It starts empty; webhook admission supplies only
            # durable tenant-scoped inbox references, not raw provider text.
            self.delivery = ChannelDeliveryService(
                kernel=self.kernel, repository=self.repository,
            )
            if self._chat_runtime is not None:
                self.execution = ChannelExecutionService(
                    repository=self.repository, chat_runtime=self._chat_runtime,
                )
                self.worker = ChannelInboxWorker(
                    repository=self.repository, execution=self.execution,
                    dispatch_outbox=self.dispatch_authorized_outbox,
                )
                self.worker.start()
            self.ingress = ChannelIngressService(
                kernel=self.kernel, repository=self.repository,
                max_native_body_bytes=self.settings.max_native_body_bytes,
                on_admitted=self.worker.submit if self.worker is not None else None,
            )
            self._initialized = True
            logger.info(
                "channel.host.dependencies_bound",
                extra={"installation_count": len(self._installed), "enabled_connections": 0},
            )
        except BaseException:
            await self.shutdown()
            raise

    async def verify_native_webhook_subscription(
        self, *, tenant_id: str, connection_id: str, verify_token: str,
    ) -> bool:
        """Check a tenant-bound installed adapter's provider subscription token.

        This is the only host authority for public GET webhook verification.
        A GET request cannot select an installation, read a Vault reference,
        grant generic plugin execution, or activate an inactive connection.
        """
        if not self._initialized or self._closed:
            raise PermissionError("Channel subscription host is unavailable")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
        ):
            raise PermissionError("Channel subscription connection unavailable")
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Channel subscription installation unavailable")
        verifier = getattr(adapter, "verify_subscription", None)
        if not callable(verifier):
            raise PermissionError("Channel adapter does not implement subscription verification")
        verified = await verifier(
            connection=connection, verify_token=verify_token,
        )
        return verified is True

    async def _whatsapp_operator_adapter(self):
        """Resolve the only installed WhatsApp transport, never a caller adapter.

        This checks local installation authority; account identity and Vault
        entitlement remain owned by ChannelActivationService and the adapter.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("WhatsApp operator host unavailable")
        installation_id = "whatsapp-cloud"
        adapter = self._installed.get(installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(installation_id) is None
            or not self.kernel.is_canonical_channel_adapter(installation_id, adapter)
        ):
            raise PermissionError("Canonical WhatsApp transport unavailable")
        return adapter

    async def list_whatsapp_operator_connections(
        self, *, tenant_id: str, user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> list[dict[str, str | int | bool]]:
        """Inspect only this tenant's persisted WhatsApp state after fresh policy."""
        await self._whatsapp_operator_adapter()
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud",
            action="channel.inspect", plan=authorized_plan,
        )
        return await self.repository.list_whatsapp_operator_connections(
            tenant_id=tenant_id,
        )

    async def inspect_whatsapp_trial_evidence(
        self, *, tenant_id: str, user_id: str, session_id: str,
        connection_id: str, external_event_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ):
        """Project one redacted durable trial after canonical inspector RBAC."""
        await self._whatsapp_operator_adapter()
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud",
            action="channel.inspect", plan=authorized_plan,
        )
        evidence = await self.repository.inspect_whatsapp_trial(
            tenant_id=tenant_id, connection_id=connection_id,
            external_event_id=external_event_id,
        )
        if evidence is not None:
            logger.info(
                "channel.whatsapp_operator.trial_inspected",
                extra={
                    "tenant_id": tenant_id, "user_id": user_id,
                    "connection_id": connection_id,
                    "correlation_id": evidence.correlation_id,
                    "inbox_status": evidence.inbox_status,
                    "outbound_status": evidence.outbound_status,
                    "provider_receipt_count": len(evidence.provider_receipt_states),
                    "policy_decision_id": authorized_plan.policy_decision_id,
                },
            )
        return evidence

    async def issue_whatsapp_self_link_challenge(
        self, *, tenant_id: str, user_id: str, session_id: str,
        connection_id: str, authorized_plan: AuthorizedExecutionPlan,
    ) -> IssuedChannelLink:
        """Issue the current principal's single-use native identity proof.

        The installed transport and tenant-scoped connection are host-owned;
        only the canonical link service generates the token and stores a digest.
        """
        await self._whatsapp_operator_adapter()
        if self.linking is None:
            raise PermissionError("Channel identity linking is unavailable")
        return await self.linking.issue_challenge(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            connection_id=connection_id, authorized_plan=authorized_plan,
        )

    async def provision_whatsapp_connection(
        self, *, tenant_id: str, user_id: str, session_id: str,
        provider_account_id: str, credential_handle: str,
        authorized_plan: AuthorizedExecutionPlan,
    ):
        """Persist a disabled tenant account; never imply Meta activation."""
        await self._whatsapp_operator_adapter()
        return await self.activation.provision(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="whatsapp-cloud",
            provider_account_id=provider_account_id,
            credential_handle=credential_handle,
            authorized_plan=authorized_plan,
        )

    async def activate_whatsapp_connection(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ):
        """Activate only the exact disabled revision after live Graph phone proof.

        Provider subscription, signed callback and delivery are separate proofs.
        """
        adapter = await self._whatsapp_operator_adapter()
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Expected WhatsApp connection revision required")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "whatsapp-cloud"
        ):
            raise PermissionError("WhatsApp connection unavailable for activation")
        if connection.enabled or connection.revision != expected_revision:
            raise ChannelActivationConflict("WhatsApp connection revision changed")
        return await self.activation.activate(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan, adapter=adapter,
            settings={"private_text_only": True},
            expected_revision=expected_revision,
        )

    async def deactivate_whatsapp_connection(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ):
        """Disable durably before stopping transport, with an exact revision."""
        adapter = await self._whatsapp_operator_adapter()
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Expected WhatsApp connection revision required")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "whatsapp-cloud"
        ):
            raise PermissionError("WhatsApp connection unavailable for deactivation")
        if not connection.enabled or connection.revision != expected_revision:
            raise ChannelActivationConflict("WhatsApp connection revision changed")
        return await self.activation.deactivate(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan, adapter=adapter,
            expected_revision=expected_revision,
        )

    async def activate_telegram_connection(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ):
        """Run canonical Telegram activation without browser-selected adapters.

        This confirms local activation and provider identity, not remote
        webhook registration or an end-to-end message round-trip.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel activation host is unavailable")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Expected connection revision required")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "telegram-bot"
            or connection.enabled or connection.revision != expected_revision
        ):
            raise PermissionError("Telegram connection is unavailable for activation")
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Canonical Telegram transport unavailable")
        # ChannelActivationService rechecks principal/RBAC/RuntimePolicy,
        # config, immutable revision and persisted CAS before returning.
        return await self.activation.activate(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan, adapter=adapter,
            settings={"private_chats_only": True},
        )

    async def register_telegram_webhook(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ) -> dict[str, bool]:
        """Explicitly register a canonical provider endpoint, never at boot.

        The HTTP mutation is not transactional with SQL. Any uncertainty must
        remain unverified and require later provider reconciliation.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel webhook registration host unavailable")
        origin = self.settings.telegram_webhook_public_origin
        if not origin:
            raise PermissionError("Channel public webhook origin not configured")
        if type(expected_revision) is not int or expected_revision < 1:
            raise PermissionError("Expected connection revision required")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "telegram-bot"
            or connection.revision != expected_revision
        ):
            raise PermissionError("Telegram webhook connection unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.webhook.register", plan=authorized_plan,
        )
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Canonical Telegram transport unavailable")
        register = getattr(adapter, "register_webhook", None)
        if not callable(register):
            raise PermissionError("Telegram registration not supported")
        # Double-check the persisted revision immediately before mutation;
        # the provider operation still needs post-call reconciliation.
        current = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if current != connection:
            raise PermissionError("Telegram webhook connection changed")
        identify_bot = getattr(adapter, "identify_bot", None)
        if not callable(identify_bot):
            raise PermissionError("Telegram bot identity verification unavailable")
        provider_bot_id = await identify_bot(connection=connection)
        if type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63:
            raise PermissionError("Telegram bot identity verification unavailable")
        claim_token = await self.repository.claim_telegram_webhook_registration(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=connection.revision, provider_bot_id=provider_bot_id,
        )
        if claim_token is None:
            raise PermissionError(
                "Telegram webhook registration pending reconciliation"
            )
        try:
            result = await register(
                connection=connection, public_origin=origin,
                expected_bot_id=provider_bot_id,
            )
            fresh = await self.repository.get_enabled_connection(
                tenant_id=tenant_id, connection_id=connection_id,
            )
            if fresh != connection or result != {
                "provider_registration_verified": True,
                "live_connected": False,
            }:
                raise RuntimeError("Telegram webhook registration unverified")
        except Exception:
            # A network timeout, uncertain response, or changed revision
            # can follow a successful remote POST. Never unlock for retry.
            try:
                await self.repository.complete_telegram_webhook_registration(
                    tenant_id=tenant_id, connection_id=connection_id,
                    expected_revision=connection.revision,
                    claim_token=claim_token, verified=False,
                )
            except Exception as exc:
                logger.error(
                    "channel.telegram.webhook.claim_uncertain",
                    extra={
                        "tenant_id": tenant_id, "connection_id": connection_id,
                        "error_type": type(exc).__name__,
                    },
                )
            raise RuntimeError("Telegram webhook registration unverified") from None
        committed = await self.repository.complete_telegram_webhook_registration(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=connection.revision,
            claim_token=claim_token, verified=True,
        )
        if committed is not True:
            raise RuntimeError("Telegram webhook registration unverified")
        logger.info(
            "channel.telegram.webhook.registration_verified",
            extra={
                "tenant_id": tenant_id, "connection_id": connection_id,
                "revision": connection.revision, "user_id": user_id,
                "policy_decision_id": authorized_plan.policy_decision_id,
            },
        )
        return dict(result)

    async def reconcile_uncertain_telegram_webhook(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ) -> dict[str, bool]:
        """Verify an expired uncertain provider registration without retry.

        This cannot delete a claim or ownership row, issue setWebhook, or
        claim live inbound/outbound delivery. A verified SQL state permits
        later separately authorized lifecycle actions.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Telegram recovery host unavailable")
        origin = self.settings.telegram_webhook_public_origin
        if not origin or type(expected_revision) is not int or expected_revision < 1:
            raise PermissionError("Telegram recovery configuration unavailable")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "telegram-bot"
            or connection.revision != expected_revision
        ):
            raise PermissionError("Telegram recovery connection unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id="telegram-bot",
            action="channel.recover", plan=authorized_plan,
        )
        claim = await self.repository.inspect_telegram_webhook_claim(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision,
        )
        if (
            not isinstance(claim, dict)
            or claim != {
                "claim_state": "uncertain",
                "claim_revision_matches": True,
                "claim_expired": True,
            }
        ):
            raise PermissionError("Telegram registration not eligible for recovery")
        adapter = self._installed.get("telegram-bot")
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest("telegram-bot") is None
            or not self.kernel.is_canonical_channel_adapter("telegram-bot", adapter)
        ):
            raise PermissionError("Canonical Telegram transport unavailable")
        verify = getattr(adapter, "verify_registration_for_recovery", None)
        if not callable(verify):
            raise PermissionError("Telegram recovery proof unavailable")
        provider_bot_id = await verify(
            connection=connection, public_origin=origin,
        )
        if type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63:
            raise PermissionError("Telegram recovery identity invalid")
        fresh = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        current_claim = await self.repository.inspect_telegram_webhook_claim(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision,
        )
        if fresh != connection or current_claim != claim:
            raise RuntimeError("Telegram recovery evidence changed")
        if await self.repository.inspect_telegram_bot_ownership(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision, provider_bot_id=provider_bot_id,
        ) is not True:
            raise PermissionError("Telegram recovery bot ownership unverified")
        committed = await self.repository.verify_uncertain_telegram_webhook_claim(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision, provider_bot_id=provider_bot_id,
        )
        if committed is not True:
            raise RuntimeError("Telegram recovery claim transition unverified")
        logger.info(
            "channel.telegram.webhook.uncertain_verified",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "revision": expected_revision,
                "user_id": user_id,
                "policy_decision_id": authorized_plan.policy_decision_id,
            },
        )
        return {
            "claim_verified": True, "claim_released": False,
            "bot_ownership_released": False, "live_connected": False,
        }

    async def inspect_telegram_registration_evidence(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int,
    ) -> dict[str, str | bool]:
        """Compare durable claim and live provider URL, without releasing a lock."""
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Telegram reconciliation inspection unavailable")
        origin = self.settings.telegram_webhook_public_origin
        if not origin or type(expected_revision) is not int or expected_revision < 1:
            raise PermissionError("Telegram reconciliation inspection unavailable")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "telegram-bot"
            or connection.revision != expected_revision
        ):
            raise PermissionError("Telegram reconciliation connection unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.inspect", plan=authorized_plan,
        )
        adapter = self._installed.get("telegram-bot")
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest("telegram-bot") is None
            or not self.kernel.is_canonical_channel_adapter("telegram-bot", adapter)
        ):
            raise PermissionError("Telegram reconciliation adapter unavailable")
        observe = getattr(adapter, "observe_registration", None)
        identify_bot = getattr(adapter, "identify_bot", None)
        if not callable(observe) or not callable(identify_bot):
            raise PermissionError("Telegram reconciliation observation unavailable")
        provider_bot_id = await identify_bot(connection=connection)
        if type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63:
            raise PermissionError("Telegram bot ownership verification unavailable")
        owned = await self.repository.inspect_telegram_bot_ownership(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision, provider_bot_id=provider_bot_id,
        )
        if owned is not True:
            raise PermissionError("Telegram bot ownership unverified")
        claim = await self.repository.inspect_telegram_webhook_claim(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision,
        )
        observation = await observe(connection=connection, public_origin=origin)
        fresh = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        current_claim = await self.repository.inspect_telegram_webhook_claim(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=expected_revision,
        )
        current_bot_id = await identify_bot(connection=connection)
        current_owner = (
            type(current_bot_id) is int
            and current_bot_id == provider_bot_id
            and await self.repository.inspect_telegram_bot_ownership(
                tenant_id=tenant_id, connection_id=connection_id,
                expected_revision=expected_revision, provider_bot_id=current_bot_id,
            ) is True
        )
        # The provider call is outside the SQL snapshot. Refuse to combine
        # evidence from different claim generations or lifecycle revisions.
        # A changed expiry is a real state transition, not a retry signal.
        if fresh != connection or current_claim != claim or not current_owner:
            raise RuntimeError("Telegram reconciliation evidence changed")
        if (
            not isinstance(claim, dict)
            or set(claim) != {
                "claim_state", "claim_revision_matches", "claim_expired",
            }
            or claim["claim_state"] not in (
                "absent", "in_flight", "uncertain", "verified",
            )
            or type(claim["claim_revision_matches"]) is not bool
            or type(claim["claim_expired"]) is not bool
            or not isinstance(observation, dict)
            or set(observation) != {
                "provider_url_matches", "provider_webhook_registered",
                "live_connected",
            }
            or any(type(observation[key]) is not bool for key in observation)
            or observation["live_connected"] is not False
            or (observation["provider_url_matches"]
                and not observation["provider_webhook_registered"])
        ):
            raise RuntimeError("Telegram reconciliation evidence invalid")
        return {
            **claim, **observation,
            "bot_identity_owner_verified": True,
            "claim_released": False,
            "reconciliation_authorized": False,
        }

    async def inspect_channel_webhook(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
    ) -> dict[str, object]:
        """Authorized, redacted live provider observation for one connection.

        The diagnostic is not proof of end-to-end message delivery and may
        never be used as an activation, send, or account-linking shortcut.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel inspection host is unavailable")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
        ):
            raise PermissionError("Channel inspection connection unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.inspect", plan=authorized_plan,
        )
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Channel inspection installation unavailable")
        inspection = getattr(adapter, "inspect_webhook", None)
        if not callable(inspection):
            raise PermissionError("Channel inspection is not supported")
        result = await inspection(connection=connection)
        if (
            not isinstance(result, dict)
            or set(result) != {
                "registered", "path_matches", "pending_update_count",
                "provider_reported_error", "endpoint_origin_verified",
            }
            or any(
                type(result[key]) is not bool for key in (
                    "registered", "path_matches", "provider_reported_error",
                    "endpoint_origin_verified",
                )
            )
            or result["endpoint_origin_verified"] is not False
            or type(result["pending_update_count"]) is not int
            or not 0 <= result["pending_update_count"] <= 1_000_000
        ):
            raise PermissionError("Channel inspection returned invalid evidence")
        return dict(result)

    async def authorize_reference(
        self, *, tenant_id: str, user_id: str, installation_id: str,
        credential_handle: str,
    ) -> bool:
        """Delegate provisioning credential integrity to the canonical Vault."""
        if not self._initialized or self._closed:
            return False
        resolver = self._resolvers.get(installation_id)
        if resolver is None or self.kernel.get_channel_activation_manifest(
            installation_id
        ) is None:
            return False
        return await resolver.authorize_reference(
            tenant_id=tenant_id, user_id=user_id,
            installation_id=installation_id,
            credential_handle=credential_handle,
        )

    async def admit_signed_personal_pairing_event(
        self, *, tenant_id: str, connection_id: str,
        headers: dict[str, str], body: bytes,
    ):
        """Admit an installed, explicitly vetted provider's signed event.

        Not an HTTP endpoint. Provider transport must pass the original bytes
        unchanged; user/browser requests cannot select an installed adapter.
        No personal pairing provider is enabled in default configuration.
        """
        from datetime import datetime, timezone

        from ai_karen_engine.services.channels.personal_pairing_callback import (
            verify_personal_pairing_callback,
        )
        from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
            PairingEvidenceDenied,
        )

        if not self._initialized or self._closed or not self.settings.enabled:
            raise PairingEvidenceDenied("Pairing gateway unavailable")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise PairingEvidenceDenied("Unrecognized pairing connection")
        installation_id = connection.installation_id
        provider_id = self.settings.personal_pairing_providers.get(installation_id)
        resolver = self._resolvers.get(installation_id)
        if (
            not provider_id or resolver is None
            or installation_id not in self._installed
            or self.kernel.get_channel_activation_manifest(installation_id) is None
            or "pairing_webhook_secret" not in self.settings.installations[installation_id]
            or not self.kernel.is_canonical_channel_adapter(
                installation_id, self._installed[installation_id],
            )
        ):
            raise PairingEvidenceDenied("No vetted pairing transport is enabled")
        owner = await self.repository.get_personal_connection_owner(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if not owner:
            raise PairingEvidenceDenied("No authorized connection owner")
        secrets = await resolver(
            tenant_id=tenant_id, credential_handle=connection.credential_handle,
        )
        secret = secrets.get("pairing_webhook_secret")
        if not secret:
            raise PairingEvidenceDenied("Missing managed-provider signing secret")
        observation = verify_personal_pairing_callback(
            body=body, headers=headers, signing_secret=secret,
            tenant_id=tenant_id, connection_id=connection_id,
            provider_id=provider_id, now=datetime.now(timezone.utc),
        )
        result = await self.repository.commit_personal_pairing_observation(
            observation=observation, user_id=owner,
            provider_vetted_and_enabled=True,
        )
        logger.info(
            "channel.personal_pairing.observation_committed",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "provider_id": provider_id,
                "connection_revision": result.connection_revision,
                "sequence": result.sequence,
                "phase": result.phase.value,
            },
        )
        return result

    async def assign_personal_connection_owner(
        self, *, tenant_id: str, connection_id: str,
        owner_user_id: str, operator_user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> bool:
        """Explicit operator action; never inferred from QR, user consent or UI.

        Ownership is immutable in this first slice. Reassignment requires
        a separately audited lifecycle with consent revocation and session
        unlink proof, not a generic upsert.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel ownership authority unavailable")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
        ):
            raise PermissionError("Channel connection not available for ownership")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=operator_user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.provision", plan=authorized_plan,
        )
        assigned = await self.repository.assign_personal_connection_owner(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=owner_user_id,
        )
        logger.info(
            "channel.connection.owner_assignment",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "user_id": operator_user_id,
                "owner_user_id": owner_user_id,
                "policy_decision_id": authorized_plan.policy_decision_id,
                "status": "assigned" if assigned else "unchanged_or_denied",
            },
        )
        return assigned

    async def place_personal_retirement_hold(
        self, *, tenant_id: str, connection_id: str,
        operator_user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int, idempotency_key: str,
    ) -> dict[str, str | int | bool]:
        """Governed local hold only; never imply vendor unlink or erasure.

        Canonical activation policy authorizes the operator. SQL serializes
        the irreversible revision fence with the hold record, then the host
        attempts process-local adapter stop. A failed stop is not hidden.
        Remote provider state remains explicitly unknown.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel retirement authority unavailable")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
        ):
            raise PermissionError("Channel connection not available for retirement")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=operator_user_id,
            session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.deactivate", plan=authorized_plan,
        )
        held = await self.repository.place_personal_retirement_hold(
            tenant_id=tenant_id, connection_id=connection_id,
            operator_user_id=operator_user_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        local_stop_attempted = False
        local_stop_succeeded = False
        if held["created_new"]:
            local_stop_attempted = True
            try:
                await self._installed[connection.installation_id].stop(
                    connection=connection,
                )
                local_stop_succeeded = True
            except Exception as exc:
                logger.warning(
                    "channel.personal_retirement.local_stop_failed",
                    extra={
                        "tenant_id": tenant_id, "connection_id": connection_id,
                        "hold_id": held["hold_id"],
                        "error_type": type(exc).__name__,
                    },
                )
        logger.info(
            "channel.personal_retirement.hold_committed",
            extra={
                "tenant_id": tenant_id, "user_id": operator_user_id,
                "connection_id": connection_id,
                "installation_id": connection.installation_id,
                "policy_decision_id": authorized_plan.policy_decision_id,
                "hold_id": held["hold_id"],
                "connection_revision": held["connection_revision"],
                "created_new": held["created_new"],
                "local_stop_attempted": local_stop_attempted,
                "local_stop_succeeded": local_stop_succeeded,
                "remote_unlink_verified": False,
                "credential_erasure_verified": False,
            },
        )
        return {
            "hold_id": held["hold_id"],
            "connection_revision": held["connection_revision"],
            "hold_recorded": True,
            "connection_enabled": False,
            "created_new": held["created_new"],
            "local_stop_attempted": local_stop_attempted,
            "local_stop_succeeded": local_stop_succeeded,
            "provider_unlinked": False,
            "credentials_erased": False,
        }

    async def _authorize_personal_pairing_consent(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> None:
        """Canonical live principal and policy gate before consent SQL."""
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel consent authority unavailable")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
        ):
            raise PermissionError("Channel connection not available for consent")
        if not await self.repository.is_personal_connection_owner(
            tenant_id=tenant_id, connection_id=connection_id, user_id=user_id,
        ):
            raise PermissionError("User is not the verified connection owner")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.consent", plan=authorized_plan,
        )

    async def inspect_owned_channel_connections(
        self, *, tenant_id: str, user_id: str, session_id: str,
        request_id: str, correlation_id: str, installation_id: str,
    ) -> dict:
        """Authorize one owner-scoped SQL inventory read, never claim live health.

        Reuse the existing channel.consent contract for personal ownership.
        One fresh action plan is bound to the actual chat session, including
        when no owned connections exist. No credentials, bot/provider IDs,
        remote URLs or connection identifiers leave this projection.
        """
        if (
            not self._initialized or self._closed or self.activation is None
            or installation_id not in self._installed
            or self.kernel.get_channel_activation_manifest(installation_id) is None
        ):
            raise RuntimeError("Channel inspection host unavailable")
        if not tenant_id or not user_id or not session_id or not request_id or not correlation_id:
            raise PermissionError("Scoped channel inspection identity required")
        await self.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=installation_id, action="channel.consent",
        )
        owned = await self.repository.list_personal_owned_connections(
            tenant_id=tenant_id, user_id=user_id,
        )
        scoped = []
        for connection in owned:
            if connection.tenant_id != tenant_id:
                raise PermissionError("Cross-tenant channel inspection denied")
            if connection.installation_id == installation_id:
                scoped.append(connection)
        if len(scoped) > 50:
            raise ValueError("Channel inspection result limit exceeded")
        enabled_count = sum(1 for item in scoped if item.enabled is True)
        status = (
            "none_owned" if not scoped
            else "owned_enabled_recorded" if enabled_count
            else "owned_disabled_recorded"
        )
        logger.info(
            "channel.personal.owner_inspection",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "installation_id": installation_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "owned_connection_count": len(scoped),
                "persisted_enabled_count": enabled_count,
                "inspection_source": "tenant_scoped_channel_owner_ledger",
            },
        )
        return {
            "inspection_source": "tenant_scoped_channel_owner_ledger",
            "owned_connection_count": len(scoped),
            "persisted_enabled_count": enabled_count,
            "latest_connection_revision": max(
                (item.revision for item in scoped), default=None
            ),
            "connection_status": status,
            "provider_registration_verified": False,
            "runtime_execution_verified": False,
            "provider_delivery_verified": False,
        }

    async def list_owned_personal_channels(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict]:
        """Owner-only status projection; never expose credentials or vendor IDs.

        Inventory is read through the same scoped SQL owner ledger and
        channel.consent policy gate as the existing per-connection status API.
        Persisted provider events are historical, not live session proof.
        """
        if not self._initialized or self._closed or self.activation is None:
            raise PermissionError("Channel inventory authority unavailable")
        connections = await self.repository.list_personal_owned_connections(
            tenant_id=tenant_id, user_id=user_id,
        )
        inventory: list[dict] = []
        for connection in connections:
            if connection.tenant_id != tenant_id:
                raise PermissionError("Personal channel tenant mismatch")
            if connection.installation_id not in self._installed:
                raise PermissionError("Channel installation no longer available")
            session_id = str(uuid4())
            plan = await self.activation.issue_action_plan(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                installation_id=connection.installation_id,
                action="channel.consent",
            )
            provider_id = self.settings.personal_pairing_providers.get(
                connection.installation_id,
            )
            status = await self.get_personal_pairing_status(
                tenant_id=tenant_id,
                connection_id=connection.connection_id,
                provider_id=provider_id or "",
                user_id=user_id,
                session_id=session_id,
                authorized_plan=plan,
            )
            # The user must retain a revocation path when a previously
            # approved provider disappears from managed-provider settings.
            # This SQL read only follows the fresh channel.consent policy
            # check above and never implies a live provider or pairing.
            active_consent_provider_ids = (
                await self.repository.list_active_personal_consent_providers(
                    tenant_id=tenant_id,
                    connection_id=connection.connection_id,
                    user_id=user_id,
                )
            )
            inventory.append({
                "connection_id": connection.connection_id,
                "installation_id": connection.installation_id,
                "provider_id": provider_id,
                "active_consent_provider_ids": active_consent_provider_ids,
                **status,
            })
        return inventory

    async def get_personal_pairing_status(
        self, *, tenant_id: str, connection_id: str, provider_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> dict:
        """Consumer-facing evidence status. Persisted != live provider status."""
        await self._authorize_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan,
        )
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if connection is None:
            raise PermissionError("Connection unavailable")
        configured = (
            self.settings.personal_pairing_providers.get(
                connection.installation_id,
            ) == provider_id
            and "pairing_webhook_secret" in self.settings.installations.get(
                connection.installation_id, frozenset(),
            )
            and connection.installation_id in self._installed
        )
        # An obsolete persisted link receipt cannot establish a live session.
        if not configured:
            return {
                "availability": "unavailable",
                "last_observed_phase": None,
                "live_connected": False,
                "qr_available": False,
                "provider_unlinked": False,
            }
        snapshot = await self.repository.get_personal_pairing_snapshot(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, provider_id=provider_id,
        )
        return {
            "availability": "configured",
            "last_observed_phase": (
                snapshot.phase.value if snapshot is not None else None
            ),
            "live_connected": False,
            "qr_available": False,
            "provider_unlinked": (
                snapshot is not None
                and snapshot.phase.value == "disconnected"
                and bool(snapshot.provider_unlink_receipt_id)
            ),
        }

    async def get_personal_pairing_risk(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str, provider_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ):
        """Read current scoped consent; never expose provider or session secrets."""
        await self._authorize_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan,
        )
        return await self.repository.get_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, provider_id=provider_id,
        )

    async def acknowledge_personal_pairing_risk(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str, provider_id: str,
        accepted: bool, policy_version: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> bool:
        """Record explicit risk agreement, never generate a QR or pair a device."""
        from ai_karen_engine.services.channels.personal_pairing_policy import (
            PERSONAL_WHATSAPP_CONSENT_VERSION,
        )

        if accepted is not True or policy_version != PERSONAL_WHATSAPP_CONSENT_VERSION:
            raise PermissionError("Current personal pairing risk acknowledgement required")
        await self._authorize_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan,
        )
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None
            or self.settings.personal_pairing_providers.get(
                connection.installation_id,
            ) != provider_id
            or "pairing_webhook_secret" not in self.settings.installations.get(
                connection.installation_id, frozenset(),
            )
        ):
            raise PermissionError("Managed personal pairing provider not configured")
        return await self.repository.acknowledge_personal_pairing_risk(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, provider_id=provider_id,
            policy_version=policy_version,
        )

    async def revoke_personal_pairing_risk(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str, provider_id: str,
        authorized_plan: AuthorizedExecutionPlan,
    ) -> bool:
        """Revoke consent; does NOT falsely assert provider session unlink."""
        await self._authorize_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=authorized_plan,
        )
        return await self.repository.revoke_personal_pairing_consent(
            tenant_id=tenant_id, connection_id=connection_id,
            user_id=user_id, provider_id=provider_id,
        )

    async def prune_unmatched_whatsapp_statuses(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
        dry_run: bool,
    ) -> dict[str, int | bool]:
        """Operator-authorized, opt-in and bounded tenant retention action.

        This is not a webhook callback, periodic worker scan, or plugin tool.
        SQL owns atomic candidate selection, receipt tombstones, and deletion;
        fresh RuntimePolicy owns the authorization. No phone IDs, Meta message
        identifiers, original payloads or credentials appear in audit logs.
        """
        if (
            not self._initialized or self._closed or self.activation is None
            or self.settings.status_retention_enabled is not True
        ):
            raise PermissionError("Channel status retention unavailable")
        if type(dry_run) is not bool:
            raise ValueError("Status retention dry-run must be boolean")
        connection = await self.repository.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id != "whatsapp-cloud"
            or connection.installation_id not in self._installed
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
        ):
            raise PermissionError("WhatsApp retention connection unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.status_prune", plan=authorized_plan,
        )
        count = await self.repository.prune_unmatched_provider_statuses(
            tenant_id=tenant_id, connection_id=connection_id,
            expected_revision=connection.revision,
            retention_days=self.settings.status_retention_days,
            limit=self.settings.status_retention_batch_limit,
            dry_run=dry_run,
        )
        logger.info(
            "channel.status_retention.completed",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "user_id": user_id,
                "connection_revision": connection.revision,
                "policy_decision_id": authorized_plan.policy_decision_id,
                "dry_run": dry_run,
                "eligible_or_deleted_count": count,
                "retention_days": self.settings.status_retention_days,
            },
        )
        return {
            "dry_run": dry_run,
            "eligible_count": count,
            "deleted_count": 0 if dry_run else count,
            "connection_revision": connection.revision,
            "retention_days": self.settings.status_retention_days,
            "batch_limit": self.settings.status_retention_batch_limit,
        }

    async def recover_inbox(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        expected_revision: int, limit: int = 100,
    ) -> int:
        """Requeue durably admitted work after explicit current policy admission.

        No process-start scan and no implicit tenant restart. The configured
        canonical installation and fresh principal must be authorized for the
        exact channel.recover capability before even reading backlog metadata.
        Individual execution still requires an atomic database claim.
        """
        if (
            not self._initialized or self._closed or self.worker is None
            or self.activation is None
        ):
            raise PermissionError("Channel recovery host is unavailable")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Positive expected connection revision required")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Channel recovery limit must be 1..1000")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
            or connection.revision != expected_revision
        ):
            raise PermissionError("Channel recovery connection is unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.recover", plan=authorized_plan,
        )
        if self.kernel.get_channel_activation_manifest(
            connection.installation_id
        ) is None:
            raise PermissionError("Channel recovery installation is unavailable")
        receipts = await self.repository.list_recoverable_inbound(
            tenant_id=tenant_id, connection_id=connection_id, limit=limit,
        )
        # A lifecycle revision may have changed while the SQL backlog was
        # being enumerated. Reject stale scheduling, leaving SQL claims intact.
        fresh = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if fresh != connection:
            raise PermissionError("Channel recovery connection changed")
        scheduled = 0
        for receipt in receipts:
            if self._closed:
                break
            if receipt.tenant_id != tenant_id:
                raise PermissionError("Channel recovery receipt tenant mismatch")
            if await self.worker.submit(receipt):
                scheduled += 1
        logger.info(
            "channel.host.recovery_scheduled",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "requested_count": len(receipts),
                "scheduled_count": scheduled,
                "policy_decision_id": authorized_plan.policy_decision_id,
            },
        )
        return scheduled

    async def dispatch_outbox(
        self, *, tenant_id: str, delivery_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan, lease_seconds: int = 90,
    ) -> bool:
        """Dispatch an existing outbox item through the bound canonical adapter.

        This method never creates authorization or selects transport based on
        native provider input. The persisted delivery selects its connection;
        ChannelDeliveryService rechecks RuntimePolicy scope, lease, revision,
        principal and native receipt evidence before recording a send.
        """
        if (
            not self._initialized or self._closed
            or self.delivery is None or self.activation is None
        ):
            raise PermissionError("Channel outbound host is unavailable")
        if not isinstance(authorized_plan, AuthorizedExecutionPlan):
            raise PermissionError("RuntimePolicy outbound plan is required")
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Outbound dispatch lease must be 3..3600 seconds")
        preflight = await self.repository.get_delivery_preflight(
            tenant_id=tenant_id, delivery_id=delivery_id,
        )
        if preflight is None:
            return False
        if preflight.user_id != user_id:
            raise PermissionError("Channel delivery principal mismatch")
        expected_session_id = ChannelDeliveryService._session_id(
            tenant_id=tenant_id, user_id=user_id,
            connection_id=preflight.connection_id,
            external_conversation_id=preflight.external_conversation_id,
        )
        if session_id != expected_session_id:
            raise PermissionError("Channel delivery session mismatch")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=preflight.connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise PermissionError("Channel outbound connection is unavailable")
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Channel outbound installation is unavailable")
        # Fresh principal/RBAC/manifest and RuntimePolicy checks are owned by
        # the existing activation authority. The delivery service independently
        # rechecks execution scope and lease just before network mutation.
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.send", plan=authorized_plan,
        )
        # Dispatch owns all final authorization and DB claim fencing. The
        # host has no right to manufacture an execution plan on its behalf.
        return await self.delivery.dispatch(
            tenant_id=tenant_id, delivery_id=delivery_id,
            adapter=adapter, authorized_plan=authorized_plan,
            lease_seconds=lease_seconds,
        )

    async def dispatch_authorized_outbox(
        self, *, tenant_id: str, delivery_id: str, user_id: str,
        session_id: str, lease_seconds: int = 90,
    ) -> bool:
        """Use fresh canonical RBAC and RuntimePolicy for one staged delivery.

        The host never accepts an untrusted permission list or a native
        transport-supplied plan. No background transport is auto-activated.
        """
        if (
            not self._initialized or self._closed or self.delivery is None
            or self.activation is None
        ):
            raise PermissionError("Channel outbound host is unavailable")
        preflight = await self.repository.get_delivery_preflight(
            tenant_id=tenant_id, delivery_id=delivery_id,
        )
        if preflight is None:
            return False
        if preflight.user_id != user_id:
            raise PermissionError("Channel delivery principal mismatch")
        canonical_session = ChannelDeliveryService._session_id(
            tenant_id=tenant_id, user_id=user_id,
            connection_id=preflight.connection_id,
            external_conversation_id=preflight.external_conversation_id,
        )
        if canonical_session != session_id:
            raise PermissionError("Channel delivery session mismatch")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=preflight.connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise PermissionError("Channel outbound connection is unavailable")
        plan = await self.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.send",
        )
        return await self.dispatch_outbox(
            tenant_id=tenant_id, delivery_id=delivery_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, lease_seconds=lease_seconds,
        )

    async def recover_outbox(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str, limit: int = 100,
    ) -> tuple[int, int]:
        """Explicit governed reconciliation of NEVER-ATTEMPTED messages.

        This method does not activate a persisted connection, resume native
        transport polling, or retry an ambiguous provider send. RuntimePolicy
        admission precedes even reading the tenant's outbox identifiers; each
        delivery independently receives a newly evaluated user-scoped plan.
        """
        if (
            not self._initialized or self._closed or self.activation is None
            or self.delivery is None
        ):
            raise PermissionError("Channel outbox recovery host is unavailable")
        if not 1 <= limit <= 1000:
            raise ValueError("Outbound recovery limit must be 1..1000")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
        ):
            raise PermissionError("Channel outbound recovery connection is unavailable")
        plan = await self.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.send",
        )
        if not plan.matches_execution_scope(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
        ):
            raise PermissionError("Outbound recovery plan scope mismatch")
        delivery_ids = await self.repository.list_unattempted_outbound(
            tenant_id=tenant_id, connection_id=connection_id, limit=limit,
        )
        dispatched = 0
        for delivery_id in delivery_ids:
            if self._closed:
                break
            preflight = await self.repository.get_delivery_preflight(
                tenant_id=tenant_id, delivery_id=delivery_id,
            )
            if preflight is None:
                continue
            if preflight.connection_id != connection_id or preflight.user_id != user_id:
                # An operator may not use their own plan to send a message
                # owned by a different tenant principal.
                logger.warning(
                    "channel.host.outbox_recovery_principal_skipped",
                    extra={"tenant_id": tenant_id, "connection_id": connection_id,
                           "delivery_id": delivery_id},
                )
                continue
            canonical_session = ChannelDeliveryService._session_id(
                tenant_id=tenant_id, user_id=user_id,
                connection_id=connection_id,
                external_conversation_id=preflight.external_conversation_id,
            )
            if canonical_session != session_id:
                continue
            if await self.dispatch_authorized_outbox(
                tenant_id=tenant_id, delivery_id=delivery_id,
                user_id=user_id, session_id=session_id,
            ):
                dispatched += 1
        logger.info(
            "channel.host.outbox_recovery_completed",
            extra={"tenant_id": tenant_id, "connection_id": connection_id,
                   "discovered_count": len(delivery_ids),
                   "dispatched_count": dispatched,
                   "policy_decision_id": plan.policy_decision_id},
        )
        return len(delivery_ids), dispatched

    async def shutdown(self) -> None:
        """Revoke process-local transport capability before database cleanup."""
        if self._closed:
            return
        self._closed = True
        self._initialized = False
        self.ingress = None
        self.activation = None
        self.linking = None
        worker = self.worker
        self.worker = None
        # A failed or cancelled worker join must not skip shutting down the
        # remaining adapters, HTTP client, Vault and PluginKernel. Preserve
        # the original shutdown failure and report it only after teardown.
        worker_failure: BaseException | None = None
        if worker is not None:
            try:
                await worker.shutdown()
            except BaseException as exc:
                worker_failure = exc
                if not isinstance(exc, asyncio.CancelledError):
                    logger.warning(
                        "channel.host.worker_shutdown_failed",
                        extra={"error_type": type(exc).__name__},
                    )
        self.execution = None
        self.delivery = None

        for name, adapter in reversed(tuple(self._installed.items())):
            try:
                await adapter.shutdown()
            except Exception as exc:
                logger.warning(
                    "channel.host.adapter_shutdown_failed",
                    extra={"installation_id": name, "error_type": type(exc).__name__},
                )
        self._installed.clear()
        self._resolvers.clear()
        try:
            await self.http_client.aclose()
        except Exception as exc:
            logger.warning(
                "channel.host.http_client_shutdown_failed",
                extra={"error_type": type(exc).__name__},
            )
        try:
            if self._owns_vault:
                await self.vault.stop()
        except Exception as exc:
            logger.warning(
                "channel.host.vault_shutdown_failed",
                extra={"error_type": type(exc).__name__},
            )
        try:
            if self._owns_kernel:
                await self.kernel.cleanup()
        except Exception as exc:
            logger.warning(
                "channel.host.kernel_cleanup_failed",
                extra={"error_type": type(exc).__name__},
            )
        logger.info("channel.host.stopped")
        if worker_failure is not None:
            raise worker_failure


__all__ = ["ChannelHostServices"]
