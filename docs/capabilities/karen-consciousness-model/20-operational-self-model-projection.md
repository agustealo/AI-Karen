# 20 | KCM-02A: Operational Self-Model read projection

[← Index](README.md) · [Previous](19-memory-consent-erasure-hooks.md)

## Status and scope

Development slice: typed read-only, evidence-gated projection, no new memory
database, model weights, CORTEX router, capability registry or API endpoint.

**Existing owner reused:** core/personalization/contracts.py already defines
SelfModel, IdentityFacet, CapabilityBelief and Provenance. KCM-02A does not
redefine these entities. The new self_model_projection.py is a small read
projection adapter inside this canonical personalization domain.

## Why this is not consciousness or another LLM

Karen Consciousness-Model is an operational **self-knowledge projection**.
It can display externally grounded facts about configured principles and
independently demonstrated capabilities. It is not subjective consciousness,
a second assistant personality, a new authority to act, or replacement for
CORTEX, RuntimePolicy, ChatRuntime or existing model providers.

User facts remain in governed memory/personalization. This first projection
is deliberately **tenant-scoped** and excludes individual-user memories
because the existing SelfModel schema has tenant_id but no user_id.

## Read contract

The caller provides:

1. An actual canonical SelfModel from Karen's authorized personalization
   source. Model metadata is not an authorization claim.
2. The independently authenticated tenant_id. Cross-tenant access is denied
   before requesting evidence. User-specific metadata is rejected.
3. An explicitly trusted SelfModelEvidenceReader implementing verify_many,
   whose canonical evidence owners enforce tenant scope, source revision,
   independent reviewer authorization and withdrawal on every read.
4. An explicit bounded evidence-reference budget, supplied through the
   existing configuration/runtime owner, not a hardcoded global allowance.

The projector deduplicates and sorts evidence references before querying
the reader, then checks their tenant, exact Karen-self subject, active status,
verification time, expiry, receipt ID and source revision. User-subject
attestations are never sufficient to justify Karen's own identity. Absent, expired, stale, disputed,
withdrawn or cross-tenant evidence cannot become an active property.

Identity facets, declared principles and limitations may use verified
configuration authority. **A claim of demonstrated capability additionally
requires independently reviewed evaluation evidence and a confirmed
canonical provenance state.** Repeated observation, a model-generated
explanation, successful tool execution or a high confidence number is
insufficient for proficiency claims.

The return shape contains the existing SelfModel type with unsupported
claims omitted, plus projection health, verified/omitted counts, reason
codes and an SHA-256 evidence-lineage fingerprint that does not include
the underlying memory or user content. The output is a temporary view,
not another persisted model or a source of truth.

## Projection health

| State | Meaning |
|---|---|
| ready | All present claims are supported by active authorized evidence |
| degraded | At least one claim verified, but one or more omitted |
| unavailable | No independently proven claim, missing reader, or exhausted budget |
| revoked | A revoked receipt was observed; whole projection is fenced |

The projection reports execution_authorized=False and
training_authorized=False in every state. It cannot create permissions,
update model weights, trigger a skill call, save a personal fact, or hide
a failed retrieval as a working capability.

## Security and observability

- No public API endpoint added. Reads must enter through a trusted runtime
  calling boundary, with tenant RBAC and user isolation enforced by the
  existing owners.
- Never trust self_model.metadata or provenance.confidence as evidence.
- Evidence readers must be durable, independently authorized and fresh;
  this slice adds the protocol and tests, **not an invented database adapter**.
- No raw evidence data or personal content is included in digests or logs.
- On reader failure, return unavailable with a reason code and empty
  verified-claim projection.
- Tests verify scope rejection before reads, revoked and expired evidence,
  unconfirmed competence, cross-user rejection, budgets, deterministic
  fingerprints, nonmutation, and no runtime or training grant.

## Acceptance and next implementation

Before a user-facing self-model is marked ready, the runtime must wire the
reader to actual authenticated Persona configuration and independently
verified outcome/evaluation records, bound the snapshot to its principal,
check current memory/consent/revocation epochs and implement freshness
invalidations. The user model and Karen self model must not be interchanged.

**Next KCM-02B:** canonical read adapters for authorized configuration,
certified outcome evidence and actual skill conditions; health/staleness
telemetry, explicit user/scope isolation and end-to-end tests. Do not
enable learning weights or autopromotion until rights, target verification,
model ancestry and trainer fencing are complete.
