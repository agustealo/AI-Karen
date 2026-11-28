"""Durable host-only lifecycle claim fence for PluginKernel installations.

This repository records preparation, not plugin execution. PluginKernel remains
the sole authority for physical state changes. No API/chat handler may interpret
a prepared or unknown operation as a successful lifecycle mutation.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import uuid
from typing import Any

from sqlalchemy import text

from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
    PluginLifecycleApprovalScope,
    PluginLifecycleKernelObservation,
)
from ai_karen_engine.persistence.postgres.transactions import (
    async_transaction_scope,
)

_PLUGIN_ID = re.compile(r"[a-z][a-z0-9_-]{0,49}\Z")
_CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")
_LIFECYCLE_LOCK_NAMESPACE = "karen-plugin-global-lifecycle-v1"


class PluginLifecycleLedgerError(RuntimeError):
    """Base error for a denied or indeterminate lifecycle claim."""


class PluginLifecycleRevisionConflict(PluginLifecycleLedgerError):
    """The installed observation is absent, stale, or already claimed."""


class PluginLifecycleApprovalRejected(PluginLifecycleLedgerError):
    """The approval is not currently valid in the exact actor scope."""


class PluginLifecycleOperationNotFound(PluginLifecycleLedgerError):
    """The operation does not belong to the requested actor/tenant scope."""


def _uuid(value: str) -> str:
    try:
        canonical = str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Valid canonical lifecycle identifier is required") from exc
    if value != canonical:
        raise ValueError("Noncanonical lifecycle identifier")
    return canonical


def _bounded(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("Valid bounded lifecycle correlation is required")
    return value


def _snapshot(row: Any) -> dict[str, Any]:
    return {
        "installation_id": str(row["installation_id"]),
        "manifest_checksum": str(row["manifest_checksum"]),
        "observed_state": str(row["observed_state"]),
        "revision": int(row["revision"]),
        "disposition": str(row["disposition"]),
        "active_operation_id": (
            str(row["active_operation_id"])
            if row.get("active_operation_id") is not None else None
        ),
    }


def _operation(row: Any) -> dict[str, Any]:
    return {
        "operation_id": str(row["operation_id"]),
        "approval_id": str(row["approval_id"]),
        "installation_id": str(row["installation_id"]),
        "tenant_id": str(row["tenant_id"]),
        "actor_user_id": str(row["actor_user_id"]),
        "action": str(row["action"]),
        "manifest_checksum": str(row["manifest_checksum"]),
        "expected_revision": int(row["expected_revision"]),
        "expected_state": str(row["expected_state"]),
        "target_state": str(row["target_state"]),
        "status": str(row["status"]),
        "request_id": str(row["request_id"]),
        "correlation_id": str(row["correlation_id"]),
    }


class PluginLifecycleLedger:
    """One application-global CAS and a tenant-scoped, single-use operation ledger.

    Only backend infrastructure may call this class. It does not provide an
    authorization grant, a mutation executor or a recovery bypass. The caller
    must obtain an authenticated, freshly authorized, action-bound plan before
    reserving. The SQL revalidates the exact approved scope independently.
    """

    @staticmethod
    async def _try_installation_lock(session: Any, installation_id: str, *, shared: bool) -> None:
        """One lock namespace for physical mutation, reservation and host use."""
        function = (
            "pg_try_advisory_xact_lock_shared" if shared
            else "pg_try_advisory_xact_lock"
        )
        locked = await session.execute(
            text(f"SELECT {function}(hashtext(:lock_namespace), hashtext(:installation_id))"),
            {"lock_namespace": _LIFECYCLE_LOCK_NAMESPACE, "installation_id": installation_id},
        )
        if locked.scalar_one() is not True:
            raise PluginLifecycleRevisionConflict(
                "Global plugin lifecycle physical execution is already locked"
            )

    @asynccontextmanager
    async def hold_enabled_execution(
        self, *, observation: PluginLifecycleKernelObservation,
    ) -> AsyncIterator[Callable[[], Awaitable[None]]]:
        """Shared durable readiness fence, not an authentication or policy grant.

        A missing revision is denied, never bootstrapped from a stale worker.
        The host supplies current kernel evidence and retains its local active
        execution marker. The connection remains pinned for the operation.
        Recheck on this same transaction before every external side effect;
        a lost database connection or changed evidence must fail closed.
        """
        if not isinstance(observation, PluginLifecycleKernelObservation):
            raise TypeError("Trusted kernel observation required")
        if observation.observed_state != "enabled":
            raise PluginLifecycleRevisionConflict("Plugin execution requires enabled evidence")
        values = {"installation_id": observation.installation_id,
                  "manifest_checksum": observation.manifest_checksum}
        async with async_transaction_scope() as session:
            await self._try_installation_lock(session, observation.installation_id, shared=True)

            async def read_ready() -> int:
                result = await session.execute(
                    text(
                        "SELECT revision FROM public.extension_lifecycle_revisions "
                        "WHERE installation_id = :installation_id "
                        "AND manifest_checksum = :manifest_checksum "
                        "AND observed_state = 'enabled' AND disposition = 'ready' "
                        "AND active_operation_id IS NULL FOR SHARE"
                    ),
                    values,
                )
                revision = result.scalar_one_or_none()
                if type(revision) is not int or revision < 1:
                    raise PluginLifecycleRevisionConflict(
                        "Enabled plugin revision is unavailable or unresolved"
                    )
                return revision

            revision = await read_ready()
            active = True

            async def revalidate() -> None:
                if not active or not session.in_transaction():
                    raise PluginLifecycleRevisionConflict("Plugin execution fence has ended")
                if await read_ready() != revision:
                    raise PluginLifecycleRevisionConflict("Plugin execution revision changed")

            try:
                yield revalidate
            finally:
                active = False

    async def initialize_observation(
        self, *, installation_id: str, manifest_checksum: str, observed_state: str
    ) -> dict[str, Any]:
        """Register one kernel-verified observation without overwriting drift.

        Only the trusted kernel host should supply these fields. This is not
        called from chat, frontend, an approval or an API route.
        """
        if (
            not isinstance(installation_id, str)
            or not _PLUGIN_ID.fullmatch(installation_id)
            or not isinstance(manifest_checksum, str)
            or not _CHECKSUM.fullmatch(manifest_checksum)
            or not isinstance(observed_state, str)
            or observed_state not in {"enabled", "disabled"}
        ):
            raise ValueError("Invalid verified plugin installation observation")
        async with async_transaction_scope() as session:
            await session.execute(
                text(
                    "INSERT INTO public.extension_lifecycle_revisions "
                    "(installation_id, manifest_checksum, observed_state) "
                    "VALUES (:installation_id, :manifest_checksum, :observed_state) "
                    "ON CONFLICT (installation_id) DO NOTHING"
                ),
                {
                    "installation_id": installation_id,
                    "manifest_checksum": manifest_checksum,
                    "observed_state": observed_state,
                },
            )
            result = await session.execute(
                text(
                    "SELECT * FROM public.extension_lifecycle_revisions "
                    "WHERE installation_id = :installation_id"
                ),
                {"installation_id": installation_id},
            )
            row = result.mappings().one()
            current = _snapshot(row)
            if (
                current["manifest_checksum"] != manifest_checksum
                or current["observed_state"] != observed_state
            ):
                raise PluginLifecycleRevisionConflict(
                    "Installed plugin observation differs from durable lifecycle evidence"
                )
            return current

    async def reconcile_manifest_observation(
        self,
        *,
        observation: PluginLifecycleKernelObservation,
        previous_checksum: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Host-only CAS primitive for an explicitly authorized, quiesced upgrade.

        The caller must fence all old workers, verify package provenance and
        obtain current kernel evidence while deployment mutation is excluded.
        This primitive is not an upgrade authorization or an automatic drift
        recovery path. It never changes activation or resolves a lifecycle claim.
        """
        if not isinstance(observation, PluginLifecycleKernelObservation):
            raise TypeError("Trusted kernel observation required")
        if (
            not isinstance(previous_checksum, str)
            or not _CHECKSUM.fullmatch(previous_checksum)
            or previous_checksum == observation.manifest_checksum
            or type(expected_revision) is not int
            or not 1 <= expected_revision < 2**63 - 1
        ):
            raise ValueError("Invalid manifest reconciliation precondition")
        values = {
            "installation_id": observation.installation_id,
            "previous_checksum": previous_checksum,
            "next_checksum": observation.manifest_checksum,
            "expected_revision": expected_revision,
            "observed_state": observation.observed_state,
        }
        async with async_transaction_scope() as session:
            await self._try_installation_lock(session, observation.installation_id, shared=False)
            result = await session.execute(
                text(
                    "UPDATE public.extension_lifecycle_revisions "
                    "SET manifest_checksum = :next_checksum, "
                    "revision = revision + 1, updated_at = clock_timestamp() "
                    "WHERE installation_id = :installation_id "
                    "AND manifest_checksum = :previous_checksum "
                    "AND revision = :expected_revision "
                    "AND observed_state = :observed_state "
                    "AND disposition = 'ready' AND active_operation_id IS NULL "
                    "RETURNING *"
                ),
                values,
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise PluginLifecycleRevisionConflict(
                    "Plugin manifest reconciliation is stale or unresolved"
                )
            return _snapshot(row)

    async def read_observation(self, installation_id: str) -> dict[str, Any] | None:
        if not isinstance(installation_id, str) or not _PLUGIN_ID.fullmatch(installation_id):
            raise ValueError("Invalid plugin installation identifier")
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    "SELECT * FROM public.extension_lifecycle_revisions "
                    "WHERE installation_id = :installation_id"
                ),
                {"installation_id": installation_id},
            )
            row = result.mappings().one_or_none()
            return _snapshot(row) if row else None

    async def reserve_approved(
        self,
        *,
        approval_id: str,
        scope: PluginLifecycleApprovalScope,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Atomically claim the global revision and consume exact approval once.

        A prepared claim deliberately leaves global state 'unresolved'. Actual
        filesystem/runtime mutation and verified commit are not implemented in
        this slice. Never auto-release or convert the claim into success.
        """
        if not isinstance(scope, PluginLifecycleApprovalScope):
            raise ValueError("Immutable plugin lifecycle approval scope required")
        approval = _uuid(approval_id)
        request = _bounded(request_id)
        correlation = _bounded(correlation_id)
        operation_id = str(uuid.uuid4())
        values = {
            "operation_id": operation_id,
            "approval_id": approval,
            "installation_id": scope.installation_id,
            "tenant_id": scope.tenant_id,
            "actor_user_id": scope.user_id,
            "action": scope.action,
            "manifest_checksum": scope.manifest_checksum,
            "expected_state": scope.expected_state,
            "target_state": "enabled" if scope.action == "enable" else "disabled",
            "expected_revision": scope.expected_revision,
            "scope": json.dumps(scope.to_record(), separators=(",", ":"), sort_keys=True),
            "intent": "plugin.lifecycle." + scope.action,
            "request_id": request,
            "correlation_id": correlation,
        }
        # Contend with active host execution before consuming any approval.
        # Lock order is global installation, then approval, then revision.
        async with async_transaction_scope(scope.tenant_id) as session:
            await self._try_installation_lock(session, scope.installation_id, shared=False)
            result = await session.execute(
                text(
                    "SELECT approval_id FROM public.runtime_approval_requests "
                    "WHERE approval_id = CAST(:approval_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:actor_user_id AS uuid) "
                    "AND status = 'approved' AND expires_at > now() "
                    "AND risk_level IN ('high','critical') "
                    "AND NULLIF(btrim(policy_decision_id), '') IS NOT NULL "
                    "AND intent = :intent "
                    "AND request_payload->'plugin_lifecycle_scope' = CAST(:scope AS jsonb) "
                    "FOR UPDATE"
                ),
                values,
            )
            if result.scalar_one_or_none() is None:
                raise PluginLifecycleApprovalRejected(
                    "No fresh, exact, approved plugin lifecycle action exists"
                )
            change = await session.execute(
                text(
                    "UPDATE public.extension_lifecycle_revisions "
                    "SET disposition = 'unresolved', "
                    "active_operation_id = CAST(:operation_id AS uuid), "
                    "updated_at = clock_timestamp() "
                    "WHERE installation_id = :installation_id "
                    "AND manifest_checksum = :manifest_checksum "
                    "AND observed_state = :expected_state "
                    "AND revision = :expected_revision "
                    "AND disposition = 'ready' AND active_operation_id IS NULL "
                    "RETURNING revision"
                ),
                values,
            )
            if change.scalar_one_or_none() is None:
                raise PluginLifecycleRevisionConflict(
                    "Plugin lifecycle revision is stale or unresolved"
                )
            # A pending FK in the same transaction refers to this row. The
            # deferred constraint refuses an incomplete or mismatched claim.
            recorded = await session.execute(
                text(
                    "INSERT INTO public.extension_lifecycle_operations "
                    "(operation_id, installation_id, approval_id, tenant_id, "
                    "actor_user_id, action, manifest_checksum, expected_state, "
                    "target_state, expected_revision, request_id, correlation_id) "
                    "VALUES (CAST(:operation_id AS uuid), :installation_id, "
                    "CAST(:approval_id AS uuid), CAST(:tenant_id AS uuid), "
                    "CAST(:actor_user_id AS uuid), :action, :manifest_checksum, "
                    ":expected_state, :target_state, :expected_revision, "
                    ":request_id, :correlation_id) "
                    "RETURNING *"
                ),
                values,
            )
            claim = _operation(recorded.mappings().one())
            consumed = await session.execute(
                text(
                    "UPDATE public.runtime_approval_requests "
                    "SET status = 'consumed', consumed_at = now(), "
                    "request_payload = '{}'::jsonb, updated_at = now() "
                    "WHERE approval_id = CAST(:approval_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:actor_user_id AS uuid) "
                    "AND status = 'approved' AND expires_at > now() "
                    "RETURNING approval_id"
                ),
                values,
            )
            if consumed.scalar_one_or_none() is None:
                raise PluginLifecycleApprovalRejected(
                    "Plugin lifecycle approval was consumed or expired"
                )
            # The entire claim + approval consume commits together, or none
            # of them become visible. This is NOT a kernel execution receipt.
            return claim

    @asynccontextmanager
    async def hold_prepared_execution(
        self,
        *,
        scope: PluginLifecycleApprovalScope,
        operation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Admit one globally fenced kernel mutation after a prepared claim.

        The caller must also prove fresh RuntimePolicy, RBAC and human approval.
        PostgreSQL's transaction-scoped advisory lock stays held through the
        caller's kernel transition and terminal CAS; no lock is a grant.
        The in_flight status is committed separately BEFORE yielding so a
        process crash cannot roll it back to a replayable prepared state.
        """
        if not isinstance(scope, PluginLifecycleApprovalScope):
            raise TypeError("Validated lifecycle approval scope required")
        operation = _uuid(operation_id)
        values = {
            "operation_id": operation,
            "installation_id": scope.installation_id,
            "manifest_checksum": scope.manifest_checksum,
            "expected_revision": scope.expected_revision,
            "expected_state": scope.expected_state,
            "target_state": "enabled" if scope.action == "enable" else "disabled",
            "action": scope.action,
            "tenant_id": scope.tenant_id,
            "actor_user_id": scope.user_id,
        }
        # This transaction owns a real PostgreSQL connection throughout the
        # physical transition. The per-process kernel lock is not sufficient.
        async with async_transaction_scope(scope.tenant_id) as fence_session:
            await self._try_installation_lock(fence_session, scope.installation_id, shared=False)
            # A separate short transaction durably writes admission before
            # side effects. Crashes after this point retain in_flight.
            async with async_transaction_scope(scope.tenant_id) as admit_session:
                updated = await admit_session.execute(
                    text(
                        "UPDATE public.extension_lifecycle_operations AS operation "
                        "SET status = 'in_flight', "
                        "execution_started_at = clock_timestamp(), "
                        "updated_at = clock_timestamp() "
                        "FROM public.extension_lifecycle_revisions AS revision "
                        "WHERE operation.operation_id = CAST(:operation_id AS uuid) "
                        "AND operation.tenant_id = CAST(:tenant_id AS uuid) "
                        "AND operation.actor_user_id = CAST(:actor_user_id AS uuid) "
                        "AND operation.installation_id = :installation_id "
                        "AND operation.manifest_checksum = :manifest_checksum "
                        "AND operation.expected_state = :expected_state "
                        "AND operation.target_state = :target_state "
                        "AND operation.action = :action "
                        "AND operation.expected_revision = :expected_revision "
                        "AND operation.status = 'prepared' "
                        "AND revision.installation_id = operation.installation_id "
                        "AND revision.manifest_checksum = operation.manifest_checksum "
                        "AND revision.observed_state = operation.expected_state "
                        "AND revision.revision = operation.expected_revision "
                        "AND revision.disposition = 'unresolved' "
                        "AND revision.active_operation_id = operation.operation_id "
                        "RETURNING operation.*"
                    ),
                    values,
                )
                row = updated.mappings().one_or_none()
                if row is None:
                    raise PluginLifecycleRevisionConflict(
                        "Exact prepared lifecycle claim is missing, stale or already started"
                    )
                admitted = _operation(row)
            # Neither exception nor cancellation permits re-entry. An
            # unresolved in_flight claim is intentionally not retryable.
            yield admitted

    async def complete_verified(
        self,
        *,
        operation_id: str,
        tenant_id: str,
        actor_user_id: str,
        observation: PluginLifecycleKernelObservation,
    ) -> dict[str, Any]:
        """CAS an in_flight operation to committed only after kernel observation.

        This is backend-only terminal persistence, not a chat execution API.
        The caller must already have executed the reserved action through the
        governed kernel path. A missing, unknown or stale operation never
        receives a success receipt or releases the global revision.
        """
        if not isinstance(observation, PluginLifecycleKernelObservation):
            raise TypeError("Trusted kernel lifecycle observation required")
        values = {
            "operation_id": _uuid(operation_id),
            "tenant_id": _uuid(tenant_id),
            "actor_user_id": _uuid(actor_user_id),
        }
        if observation.operation_id != values["operation_id"]:
            raise PluginLifecycleRevisionConflict(
                "Kernel lifecycle evidence does not match the reserved operation"
            )
        async with async_transaction_scope(values["tenant_id"]) as session:
            # Lock the operation first. Concurrent unknown/complete attempts
            # serialize before touching the application-global revision.
            result = await session.execute(
                text(
                    "SELECT * FROM public.extension_lifecycle_operations "
                    "WHERE operation_id = CAST(:operation_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND actor_user_id = CAST(:actor_user_id AS uuid) "
                    "AND status = 'in_flight' FOR UPDATE"
                ),
                values,
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise PluginLifecycleOperationNotFound(
                    "Prepared lifecycle operation unavailable in actor scope"
                )
            operation = _operation(row)
            if (
                observation.installation_id != operation["installation_id"]
                or observation.manifest_checksum != operation["manifest_checksum"]
                or observation.observed_state != operation["target_state"]
            ):
                raise PluginLifecycleRevisionConflict(
                    "Observed kernel state does not match approved transition"
                )
            expected_revision = operation["expected_revision"]
            state_values = {
                **values,
                "installation_id": operation["installation_id"],
                "manifest_checksum": operation["manifest_checksum"],
                "expected_state": operation["expected_state"],
                "target_state": operation["target_state"],
                "expected_revision": expected_revision,
            }
            change = await session.execute(
                text(
                    "UPDATE public.extension_lifecycle_revisions "
                    "SET observed_state = :target_state, "
                    "revision = revision + 1, "
                    "disposition = 'ready', active_operation_id = NULL, "
                    "updated_at = clock_timestamp() "
                    "WHERE installation_id = :installation_id "
                    "AND manifest_checksum = :manifest_checksum "
                    "AND observed_state = :expected_state "
                    "AND revision = :expected_revision "
                    "AND disposition = 'unresolved' "
                    "AND active_operation_id = CAST(:operation_id AS uuid) "
                    "RETURNING revision"
                ),
                state_values,
            )
            new_revision = change.scalar_one_or_none()
            if new_revision != expected_revision + 1:
                raise PluginLifecycleRevisionConflict(
                    "Global plugin lifecycle revision was not exclusively claimed"
                )
            final = await session.execute(
                text(
                    "UPDATE public.extension_lifecycle_operations "
                    "SET status = 'verified_committed', "
                    "updated_at = clock_timestamp() "
                    "WHERE operation_id = CAST(:operation_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND actor_user_id = CAST(:actor_user_id AS uuid) "
                    "AND status = 'in_flight' "
                    "RETURNING *"
                ),
                state_values,
            )
            recorded = final.mappings().one_or_none()
            if recorded is None:
                raise PluginLifecycleRevisionConflict(
                    "Verified lifecycle receipt was not committed"
                )
            # Both updates commit or roll back together. This receipt still
            # cannot be projected into consumer chat until every mutation path
            # shares the global fence and fresh policy is enforced at runtime.
            return {
                **_operation(recorded),
                "prior_revision": expected_revision,
                "next_revision": int(new_revision),
                "verification_source": "plugin_kernel",
            }

    async def mark_unknown(
        self,
        *,
        operation_id: str,
        tenant_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        """Retain unresolved revision after an uncertain outcome, no retries."""
        values = {
            "operation_id": _uuid(operation_id),
            "tenant_id": _uuid(tenant_id),
            "actor_user_id": _uuid(actor_user_id),
        }
        async with async_transaction_scope(values["tenant_id"]) as session:
            result = await session.execute(
                text(
                    "UPDATE public.extension_lifecycle_operations "
                    "SET status = 'unknown', updated_at = clock_timestamp() "
                    "WHERE operation_id = CAST(:operation_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND actor_user_id = CAST(:actor_user_id AS uuid) "
                    "AND status IN ('prepared', 'in_flight') "
                    "RETURNING *"
                ),
                values,
            )
            row = result.mappings().one_or_none()
            if row is None:
                existing = await session.execute(
                    text(
                        "SELECT * FROM public.extension_lifecycle_operations "
                        "WHERE operation_id = CAST(:operation_id AS uuid) "
                        "AND tenant_id = CAST(:tenant_id AS uuid) "
                        "AND actor_user_id = CAST(:actor_user_id AS uuid)"
                    ),
                    values,
                )
                row = existing.mappings().one_or_none()
            if row is None:
                raise PluginLifecycleOperationNotFound(
                    "Lifecycle operation is unavailable in this actor scope"
                )
            record = _operation(row)
            if record["status"] != "unknown":
                raise PluginLifecycleLedgerError(
                    "Only a prepared, in_flight or unknown lifecycle claim may be marked unknown"
                )
            return record

    async def read_operation(
        self, *, operation_id: str, tenant_id: str, actor_user_id: str
    ) -> dict[str, Any] | None:
        values = {
            "operation_id": _uuid(operation_id),
            "tenant_id": _uuid(tenant_id),
            "actor_user_id": _uuid(actor_user_id),
        }
        async with async_transaction_scope(values["tenant_id"]) as session:
            result = await session.execute(
                text(
                    "SELECT * FROM public.extension_lifecycle_operations "
                    "WHERE operation_id = CAST(:operation_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND actor_user_id = CAST(:actor_user_id AS uuid)"
                ),
                values,
            )
            row = result.mappings().one_or_none()
            return _operation(row) if row else None


__all__ = [
    "PluginLifecycleApprovalRejected",
    "PluginLifecycleLedger",
    "PluginLifecycleLedgerError",
    "PluginLifecycleOperationNotFound",
    "PluginLifecycleRevisionConflict",
]
