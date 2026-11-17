# KCHAT-AUTH-05B2B2A: canonical embedding admission is mandatory

**Status:** source candidate, not complete KCHAT-AUTH-05B2. Depends on
merged PR #991 and caller census PR #996.

## Scope and retained ownership

The existing `ModelManager.generate_embedding` is the sole canonical,
real-model-only embedding execution surface being repaired here. It now
requires the original, authenticated `GovernedToolModelAdmission` before
reading encoder state or invoking `embed_authoritative`; an absent/forged
grant fails closed. The original `AuthorizedExecutionPlan`,
`ChatExecutionContext` and `ExecutionBudgetMeter` are reused unchanged.

The caller census found two static Core production invocations of
`ModelManager.generate_embedding`, both already passing an authenticated
admission via `LLMUtils`. No second plan, meter, router, authorization
framework, or embedding fallback was introduced.

## Behavioral contract

- Missing/invalid grant, foreign tenant, or replaced original budget:
  permission denial before encoder calls, quota consumption or fallback.
- Valid grant with bad input, unavailable encoder, or unsupported kwargs:
  explicit failure before budget reservation.
- Valid registered local encoder: one actual real-model attempt, charged
  once to the original shared meter, invoked off the event loop.
- No new network permission; existing provider allow/deny and model
  restrictions remain enforced by Core admission.

The public direct `ModelManager.generate_chat` compatibility branch,
`invoke_provider` and `invoke_embedding` raw helpers, raw local
OpenAI-compatible client, and `EmbeddingManager` legacy hashed/simple
fallbacks are **still outstanding**. No claim is made that all embedding
consumers have migrated, or that final DNS/socket egress is certified.

## Proof

`tests/core/model_runtime/test_model_execution_truth.py` retains real
encoder worker-thread proof under an authenticated grant.

`tests/core/model_runtime/test_governed_core_inference_admission.py`
asserts zero encoder calls on missing/forged/foreign grant and equal-value,
different-object meters, and retains exact per-vector quota/provenance
checks on the working Core facade. Chat System Burn already runs both
suites. Full exact-head Main Quality, Ollama, Medusa, First-Boot and
independent reviewer acceptance are required before merging.

## P1 original-object lineage repair

Independent review found that checking `meter.budget is plan.budget` alone
did not reject a fresh `ExecutionBudgetMeter` wrapping the same original
budget. ChatRuntime now binds the **original plan and meter object references**
to its existing authenticated `ChatExecutionContext` on both direct and
streaming paths before execution. Neither `dataclasses.replace` nor
`dataclasses.asdict` copies that private request-only lineage.

The Core admission validator requires the exact bound plan/meter identity.
The existing trusted Medusa handoff compares its deserialized plan against
the original bound plan and reuses that original object; a narrowed specialist
plan must be individually registered against the same meter and cannot widen
its permitted tools/plugins/agents. No second policy issuer or budget meter
was added.

Regression tests now exercise fresh meters sharing the original budget,
copied plans, cloned contexts, exhausted quotas, and valid narrowed Medusa
plans. A valid copied plan without explicit trusted child registration is
never authorized.

Medusa's serialized handoff compares dataclass-normalized values before
recovering the original request-owned plan, because nested degradation and
provenance data become dictionaries in the transfer payload. An empty root
allowlist retains its existing unspecified semantics; nonempty root lists
cannot be widened by specialist child registration.

### RuntimePolicy-issued model-execution provenance

A fresh request/execution ID is **not** proof of permission. The former weak
registry of context IDs was inadequate: callers could change the execution ID,
copy the plan and budget, and reset the model quota. It has been removed.

The *existing* `RuntimePolicyEnforcer.evaluate` retains the exact allowed
`PolicyDecision` object it actually returned. `RuntimeDecisionPipeline.decide`
can attach that identity to the **original authenticated context** only after
a successful, scope-matching policy evaluation. The policy object is bound to
that context once. The identity proof is private runtime state, not a
serialized or caller-provided ID, signing key, SDK option or UI permission.

On both direct and stream chat paths, original plan/meter binding requires
that issuer proof, the same original policy decision, request principal,
tenant/session/correlation scope, and an allowed model-call budget no greater
than the policy decision permits. The existing Core admission gate then
enforces exact plan and meter object identities and accounts all accepted
model attempts against the single original meter. `dataclasses.replace`
of a context or policy decision does not carry private issuer provenance;
copying or renaming the plan and budget cannot register a new allowance.

The existing Medusa handoff continues to reconstruct a serialized plan only
for *comparison*, then uses the exact original authorized plan and meter.
Authenticated standalone Medusa execution requires the same verified
RuntimePolicy-issued decision and may establish its own first meter only
against its original policy-bound context; standalone caller-supplied plan
dictionaries alone do not grant model execution.

**Not yet certified:** this is a source candidate with an updated
real-evaluator regression plus the exact-head CI and independent security
review gates outstanding. Its issuer provenance does not replace the ingress
principal, authorize arbitrary untrusted in-process Python code, migrate
the remaining raw model invocation paths, or constitute host-level egress
attestation. The separate mandatory governed chat-generation and fallback
migration remains open.

### Compatibility checks after independent reviewer findings

The decision pipeline may still return **non-executing diagnostic policy
analysis** without an authenticated principal, but it never attaches model
execution provenance in that case. A real execution requires the ingress
principal again at initial plan/meter binding.

An authorized policy with `max_model_calls=0` may bind a tool-only plan.
The shared meter still denies every model attempt and no inference is
fabricated. No permission or quota is inferred from the mere existence
of a RuntimePolicy ID.

Shared-budget Medusa can accept a *narrowed* serialized derivative, but
only when the sole differences from the original in-process policy plan
are the tool/plugin/agent allowlists. All other fields are compared
against the original by dataclass-normalized value. The narrowed
derivative is explicitly registered with the **original** meter; it never
recreates a second quota. Each downstream specialist is restricted
against the actual handoff-narrowed allowlists as well as the root,
preventing widened sibling permissions. Unchanged handoffs still
recover the exact root plan object.

Targeted regressions cover these three cases, an attempted widened
serialized handoff, a truly evaluated RuntimePolicy decision, and
copied-plan/budget/context replay. Exact-head CI, independent review and
post-merge acceptance remain required; no release claim is made here.

### Mutable budget field containment

A valid original admission must not be able to expand quota by mutating the
`AuthorizedExecutionPlan.budget` dataclass before its next call.
`ExecutionBudgetMeter`, the existing request-owned quota authority, now
snapshots **all** original policy limits at construction in a private
read-only mapping. Later changes to `plan.budget.max_model_calls`,
`max_external_requests`, duration or tool/token bounds never change
reservation limits or the original shared object identity. No extra meter
was introduced. Tests exercise post-admission budget mutation, external
request caps, and rejection without added model usage. This does not
constitute arbitrary in-process Python sandboxing.
