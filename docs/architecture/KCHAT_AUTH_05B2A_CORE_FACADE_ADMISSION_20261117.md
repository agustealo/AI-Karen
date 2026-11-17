# KCHAT-AUTH-05B2A: governed inference façades and one original meter

**Status:** candidate awaiting CI, independent review, merge and post-merge verification.
**Dependency:** #990 merged. Scope is intentionally limited to existing Core inference façades.

## Source of truth

The RuntimePolicy-issued AuthorizedExecutionPlan, authenticated ChatExecutionContext
and original shared ExecutionBudgetMeter are **passed in** to a Core-owned
GovernedToolModelAdmission. No SDK, plugin, LLMUtils or InferencePort can mint
a new policy decision, construct a new plan, or renew a caller's budget.

The original admission class has been moved out of the optional LangChain
adapter to core/model_runtime/governed_model_admission.py; the original
GovernedToolModelAdmission name remains an import alias for Deep Agents,
so there is no second admission implementation.

- Local and external attempts recheck user, tenant, session, policy decision,
  request and correlation identity; an active verified ingress principal must
  match. Meter.budget must be the exact plan.budget object, not an equal copy.
- Existing provider constraints and RuntimePolicyEnforcer's external gate are
  reused. Denied attempts spend zero model/external quota.
- Each accepted governed attempt reserves exactly once on the original
  ExecutionBudgetMeter, including local embeddings and concurrent requests.
  Retry attempts require another reservation.
- ModelManager's governed calls validate the scope before provider selection
  and reserve before warming or invoking the model. InferencePort denies missing
  admission before calling the manager.
- LLMUtils no longer accepts injected raw executable provider objects or
  returns a borrowed client. Generation and embeddings delegate to ModelManager
  using the same admission, not a parallel provider selection or direct method
  call. Caller user_ctx dictionaries never issue grants.
- Raw compatibility external HTTP remains fail closed, even when supplied a
  purported grant, until the canonical governed external provider transport
  can be used end-to-end. An ungoverned hostname/HTTP compatibility shim can
  never be promoted with a boolean escape hatch.

## Explicit outstanding gaps (KCHAT-AUTH-05B2B)

Legacy direct ModelManager.generate_chat without an admission argument, public
invoke_provider / invoke_embedding helpers, and direct raw-client or
EmbeddingManager object calls still exist. They require a repository-wide
active caller audit, migration and final fail-closed enforcement. Do not claim
all local inference is governed based on this scoped façade migration.

ExpressionGateway and Deep Agents retain their existing trusted charging
paths. **Do not double-charge** ExpressionGateway's pre-reserved first call,
and do not create a second meter for LangGraph children or plugin calls.

Also outstanding: request-bound governed external compatibility execution
through the canonical transport, raw health-probe network eligibility, DNS
resolution/socket pinning and host-level packet capture.
