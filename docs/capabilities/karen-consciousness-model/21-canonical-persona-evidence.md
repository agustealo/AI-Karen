# 21 | KCM-02B1: Canonical system Persona evidence and claim binding

[← Index](README.md) · [Previous](20-operational-self-model-projection.md)

## Scope

KCM-02A provided a generic, evidence-filtered read-only SelfModel
projection. KCM-02B1 connects its **configuration** evidence to the
actual versioned \`SYSTEM_PERSONAS\` objects defined by
\`core/persona/contracts.py\`. It deliberately does not claim that a
configured Persona is the active choice of any user or evidence that Karen
can successfully perform a task.

This is an initial trusted source adapter, not a full deployed self-model,
a new memory store, an LLM, a second Persona registry, or training permission.

## Architecture owners

| Subject | Owner | KCM-02B1 behavior |
|---|---|---|
| Built-in Persona definitions | \`core/persona/contracts.py\` \`SYSTEM_PERSONAS\` | Re-read source on every verification, no copied registry |
| Karen SelfModel and provenance contracts | \`core/personalization/contracts.py\` | Reuse existing \`SelfModel\` and \`IdentityFacet\` |
| Evidence filtering | \`core/personalization/self_model_projection.py\` | Check scope, activity, claim binding and expiry |
| Read-only source projection | \`core/personalization/system_persona_evidence.py\` | Build and verify temporary system-Persona style facts |
| User-selected/custom Personas | Existing PersonaService and user preference repositories | **Not read or projected** |
| Independently assessed skills | Governed evaluation and outcomes owners | **Not certified by this adapter** |

## Why evidence references alone are insufficient

A valid configuration reference saying that the built-in Assistant Persona
uses a friendly default tone cannot be reused to assert "Karen has advanced
deployment capability." The first version of the generic projection
verified the presence of source references, not the actual claim they
supported.

KCM-02B1 adds a canonical \`claim_sha256\` binding to each evidence receipt.
The projector recomputes a deterministic digest from the actual claimed
property (domain, key, value, description, limitation flag) or capability
belief (name, type, description, self-reference), and rejects receipts
whose digest does not match. Missing old-style receipt bindings fail closed.

The system Persona reader obtains a source revision SHA-256 from the **current
canonical Persona values**, excluding only generated created/updated
timestamps. A changed Persona or style configuration immediately invalidates
cached old claims. This is in-process source integrity, not a claim of
cryptographic signing by an external authority.

## What the implementation can truthfully report

Examples of configuration assertions:

- A built-in system Persona named "assistant" is configured with its
  current default tone, language and verbosity.
- Other active built-in system Personas have their own configured
  defaults, verified against the live canonical registry.

These are availability/configuration observations. They do **not** claim:

- Which Persona a specific user selected.
- Karen's current provider, model, capability or plugin availability.
- Independent success at coding, research, deployment or other skills.
- A user's memories, traits or preferences.
- Human-like awareness or subjective consciousness.

The projected facets use \`IdentityDomain.PREFERENCE\` with namespaced
system Persona keys. \`CapabilityBelief\` remains empty. The result is
tenant-bound even though built-in Persona definitions are global.

## Fail-closed contracts

- An authenticated tenant UUID must be supplied by the existing runtime.
  No new public endpoint or caller-supplied identity authority is created.
- Only active \`is_system_persona\` source entries are eligible.
  Duplicated or malformed source IDs are rejected.
- A user-created Persona is excluded from the tenant-wide SelfModel.
- Receipts are typed \`CONFIGURATION\` and \`KAREN_SELF\`, never
  \`INDEPENDENT_EVALUATION\` or \`USER\`.
- Source revision and claim digest are recomputed on every read.
- Evidence references must be recognized, unique and bounded by the
  caller's configured projector budget.
- If the verifier fails or a claim mismatches, the projector returns
  \`unavailable\` or \`degraded\`, never a fabricated ready response.
- \`execution_authorized=False\` and \`training_authorized=False\`
  are fixed output invariants.

Even when every built-in configuration claim is current and projection
health is \`ready\`, **only the configuration subview** is ready. KCM itself
is not a production-validated self-aware assistant, and this result grants
no permission to act.

## Proof

Focused tests verify real canonical Persona values, two-tenant separation,
configuration revision drift, prevention of receipt reuse for forged
properties, refusal of configuration-as-skill escalation, exclusion of
private custom Personas, invalid principals, unknown references and budget
failures. The existing KCM-02A projector regression tests now require
claim-bound evidence receipts.

The dedicated KCM CI workflow includes both test suites, with exact-head
backend, frontend, cognition and first-boot gates required for merge.

## Next: KCM-02B2

- Identify an actually independent, durable **skill certification** authority
  and validate its reviewer, source, task-condition and revocation lineage.
- Do not promote \`outcome_records\` execution success, thumbs-up or
  self-generated confidence into skill evidence.
- Add user-scoped projections only after an explicit, canonical user identity
  is present in the contract and tenant+user isolation is proven.
- Bind operational health to capability/provider/plugin availability and
  source deletion epochs, then integrate through the authorized runtime.
- Preserve CORTEX decisions and RuntimePolicy as the final action gate.
