# Model Lifecycle: Canonical Ownership and Delivery Plan

## Objective

Make AI-Karen's local model experience a complete, auditable lifecycle:
**discover → evaluate → authorize → acquire → verify → register → activate → select → execute → maintain → retire**.
A downloaded file is not a healthy runtime model, and a catalog entry is not an execution grant.

## Existing owners (retain and reuse)

| Responsibility | Canonical owner | Evidence |
| --- | --- | --- |
| Runtime catalog, availability, model/provider choice | Central runtime registry, config, router and ChatRuntime | Existing model-runtime APIs and provider selection |
| Source metadata, revisions, licenses, compatibility | Model orchestrator and download control service | `model_download_control_service.py` |
| Durable queue, claims, concurrency, retry, leases | PostgreSQL download repository and long-running worker | `model_download_repository.py`, `model_download_worker.py` |
| Publication rollback and recovery | Publication recovery service | `model_download_publication_recovery.py` |
| Consumer acquisition and inventory | Existing ModelDownloads component | `ModelDownloads.tsx` |
| Agent/model request hints | assistant-ui → AG-UI → ChatRuntime | chat selector PR #542; never a second router |
| Permission, tenant, and admin checks | Authenticated ingress + RuntimePolicy + persistence constraints | Model-download router remains admin-scoped |

## Confirmed gaps and required phases

### P0: Honest access and lifecycle visibility
1. Keep admin-scoped download/job/policy/storage routes gated. Do **not** expose global job data to regular users through a visible tab.
2. Show the lifecycle sequence and its observed stage evidence in the existing model library UI. Preserve precise unavailable/unknown states.
3. Define a distinct non-admin API projection before expanding regular-user access: scope owned jobs by tenant and user, redact storage paths, credentials, administrative policy and unrelated job metadata.
4. Verify Settings navigation and active role propagation with UI tests. Product visibility is not an authorization check.

### P1: Acquisition contracts
1. Treat Hugging Face / Ollama / local imports as source adapters to one validated download/install contract, not parallel download managers.
2. Resolve immutable source identity, revision, expected format, file manifest, checksums, license/gating decision, trust-remote-code policy and minimum resources before job creation.
3. Preserve idempotent queueing, competing worker claims, cancellation and target exclusivity. Explicit operator override is audited, never inferred.
4. Expose truthful progress phases (metadata, downloading, validating, publishing, failed, quarantined, installed); add reason-coded retry and repair actions, not blind retry loops.

### P2: Installation and activation authority
1. Verify checksums and file manifest in quarantine, perform safe atomic publication, then register models in the single runtime registry.
2. Track separate lifecycle state and readiness: `downloaded`, `verified`, `registered`, `loadable`, `healthy`, `selected`. Never report a model ready solely because files exist.
3. Perform a capability-aware load/health probe with bounded resources and deadlines; report provider, runtime engine, effective model and failure cause.
4. After an authorized successful probe, expose the model to ChatRuntime's backend-supplied catalog. UI must not self-promote the selected model.

### P3: Resource-aware operations and governance
1. Quota and capacity gate by tenant, provider, disk space, RAM/VRAM, download bandwidth and configured concurrency. Keep defaults/env overrides in central config.
2. Reference-count or check active chat sessions and model bindings before unloading or deletion; publish explicit rollback/recovery receipts.
3. Require RBAC and audit for installs, removal, shared storage, policy mutation, unsafe code execution, and administrator overrides.
4. Add telemetry on queue wait, transfer throughput, verification, health probes, failures and resource pressure with correlation and job IDs, without leaking tokens, local paths or user content.
5. Add operator interventions for stale leases, recovery-needed publications and orphaned blobs, always bounded and explicitly authorized.

### P4: Delivery and operational proof
1. Unit tests for validation, policy, revisions, license, filesystem traversal and incompatible artifacts.
2. Integration tests for concurrent claims, cancellation, checkpoint resume, publication crash recovery, tenant ownership, quotas and degraded worker availability.
3. Contract tests for authenticated consumer inventory, installer/read-only split, unavailable catalog, state transitions, chat selection and actual execution receipt.
4. UI tests for new users, empty library, downloads disabled, queue in progress, failed verification, worker offline and installed-but-unavailable model.
5. Exact-head CI: Python compile/ruff/pytest, frontend lint/typecheck/test/build, Docker Compose config. Real model/hardware proof remains manual and must never silently block ordinary PRs.

## Release gates

- **Library usable:** Backend-scoped discovery + lifecycle status visible, no cross-tenant job disclosure.
- **Download usable:** Source/revision/license verified, durable job and reason-coded failure, healthy worker or honest unavailability.
- **Select usable:** Registered healthy model in authorized provider catalog; selected intent recorded; actual runtime receipt verified.
- **Delete usable:** Proven no live references or explicitly governed unload; rollback and audit confirmed.

## Risk and migration

Never make `/api/models/download/jobs` public as-is: its current API path lists durable jobs without per-user filtering because it is protected by the application-level runtime-admin router. Exposing the UI alone does not establish safe consumer functionality. Migrate one endpoint at a time under explicit authorization, ownership filtering and tests. Preserve the existing files/queues/migrations rather than creating a second model installer.
