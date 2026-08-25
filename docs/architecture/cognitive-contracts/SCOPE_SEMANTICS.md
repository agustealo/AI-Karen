# Scope Semantics

For all public cognitive contracts, identify whether they require tenant_id, user_id, session_id, conversation_id, or project_id.

## Scope contracts

| Scope class | Definition | Required fields |
| ----------- | ---------- | --------------- |
| `GlobalScope` | System-wide, not user-specific | None |
| `TenantScope` | Tenant-isolated | `tenant_id` |
| `UserScope` | User-specific within tenant | `tenant_id`, `user_id` |
| `ConversationScope` | Conversation-specific | `tenant_id`, `user_id`, `conversation_id` |
| `ProjectScope` | Project-specific | `tenant_id`, `user_id`, `project_id` |
| `SessionScope` | Session-specific | `tenant_id`, `user_id`, `session_id` |

## Public contract scope audit

| Contract | File | Scope class | tenant_id | user_id | session_id | conversation_id | project_id | Issues |
| -------- | ---- | ----------- | --------- | ------- | ---------- | --------------- | ---------- | ------ |
| MemoryClaim | memory/contracts.py | UserScope | missing | missing | - | - | - | **No scope fields** |
| SalienceScore | memory/contracts.py | Global | - | - | - | - | - | OK |
| SelfModel | memory/contracts.py | UserScope | missing | missing | - | - | - | **No scope fields** |
| UserModel | memory/contracts.py | UserScope | missing | missing | - | - | - | **No scope fields** |
| RelationshipModel | memory/contracts.py | UserScope | missing | missing | - | - | - | **No scope fields** |
| ProspectiveMemory | memory/contracts.py | UserScope | missing | missing | - | created_from | - | **No scope fields** |
| MemoryEntry | memory/types/base.py | UserScope | via metadata | via metadata | via metadata | via metadata | - | OK (via MemoryMetadata) |
| BeliefClaim | reasoning/belief/contracts.py | UserScope | str | str \| None | - | - | - | OK |
| Evidence | reasoning/belief/contracts.py | UserScope | str | str \| None | - | - | - | OK |
| ClaimTemporalValidity | reasoning/belief/contracts.py | Global | - | - | - | - | - | OK |
| MetaCognitiveRequest | reasoning/meta/contracts.py | TenantScope | str = "default" | - | - | - | - | **Ambiguous default** |
| ReasoningRequest | reasoning/contracts.py | ConversationScope | str | str | - | Optional[str] | - | OK |
| ReasoningEvidence | reasoning/contracts.py | TenantScope | str = "default" | - | - | - | - | **Ambiguous default** |
| ContextCandidate | context/contracts.py | Global | - | - | - | - | - | OK |
| SalienceContext | adaptive/salience/contracts.py | SessionScope | str = "default" | str \| None | str \| None | - | - | **Ambiguous defaults** |
| SalienceSignal | adaptive/salience/contracts.py | TenantScope | str = "default" | - | - | - | - | **Ambiguous default** |
| MemorySalienceSignal | adaptive/salience/contracts.py | TenantScope | str = "default" | - | - | - | - | **Ambiguous default; note: uses memory_id field** |
| GoalSalienceAdjustment | adaptive/salience/contracts.py | TenantScope | str = "default" | - | - | - | - | **Ambiguous default** |
| AdaptiveContext | adaptive/contracts.py | UserScope | str = "default" | str | str \| None | - | - | **Ambiguous defaults** |
| UserStateSnapshot | adaptive/contracts.py | UserScope | str = "default" | str | str \| None | - | - | **Ambiguous defaults** |
| BehaviorPatternSummary | adaptive/contracts.py | UserScope | str = "default" | str | - | - | - | **Ambiguous defaults** |
| BehaviorSelectionContext | cortex/behavior/contracts.py | SessionScope | str = "default" | str \| None | str \| None | - | - | **Ambiguous defaults** |
| UserContext | cortex/contracts.py | UserScope | Optional[str] | str | Optional[str] | Optional[str] | - | OK (optional tenant_id) |
| IntentSignal | cortex/contracts.py | Global | - | - | - | - | - | OK |
| KireSignal | cortex/contracts.py | Global | - | - | - | - | - | OK |
| Goal | personalization/goals/contracts.py | UserScope | str | str \| None | - | - | - | OK |
| Intention | personalization/goals/contracts.py | UserScope | str | str \| None | - | - | - | OK |
| Commitment | personalization/goals/contracts.py | UserScope | str | str \| None | - | - | - | OK |
| ProspectiveMemory | personalization/goals/contracts.py | UserScope | str = "" | str \| None | - | - | - | **Empty string default** |
| GoalEvidence | personalization/goals/contracts.py | UserScope | str = "" | str \| None | - | - | - | **Empty string default** |
| PreferenceRecord | personalization/contracts.py | UserScope | str | str | - | - | - | OK |
| SelfModel | personalization/contracts.py | TenantScope | str | - | - | - | - | **Missing user_id** |
| UserModel | personalization/contracts.py | UserScope | str | str | - | - | - | OK |
| RelationshipModel | personalization/contracts.py | UserScope | str | str | - | - | - | OK |
| ExperienceObservation | adaptive/learning/experience/contracts.py | UserScope | str = "default" | str \| None | - | - | - | **Ambiguous default** |
| LearningSignal | adaptive/learning/experience/contracts.py | UserScope | str = "default" | str \| None | - | - | - | **Ambiguous default** |

## Ambiguous defaults requiring review

| Contract | Field | Current default | Risk |
| -------- | ----- | --------------- | ---- |
| MetaCognitiveRequest | tenant_id | `"default"` | Security-sensitive meta-cognition defaults to default tenant |
| ReasoningEvidence | tenant_id | `"default"` | Evidence inherits default tenant |
| SalienceContext | tenant_id | `"default"` | Salience signals inherit default tenant |
| SalienceSignal | tenant_id | `"default"` | Cross-tenant signal leakage possible |
| MemorySalienceSignal | tenant_id | `"default"` | Cross-tenant memory salience leakage possible |
| GoalSalienceAdjustment | tenant_id | `"default"` | Cross-tenant goal adjustment possible |
| AdaptiveContext | tenant_id | `"default"` | Adaptive decisions default to default tenant |
| UserStateSnapshot | tenant_id | `"default"` | User state defaults to default tenant |
| BehaviorPatternSummary | tenant_id | `"default"` | Behavior patterns default to default tenant |
| BehaviorSelectionContext | tenant_id | `"default"` | Behavior selection defaults to default tenant |
| ExperienceObservation | tenant_id | `"default"` | Learning observations default to default tenant |
| LearningSignal | tenant_id | `"default"` | Learning signals default to default tenant |
| ProspectiveMemory (goals) | tenant_id | `""` (empty string) | Empty string is falsy but not None |
| GoalEvidence | tenant_id | `""` (empty string) | Empty string is falsy but not None |

## Recommendation

1. Remove `"default"` tenant_id defaults from all security-sensitive contracts.
2. Require explicit `tenant_id: str` (no default) in all UserScope+ contracts.
3. Add `project_id` to contracts that need ProjectScope.
4. Standardize optional scope fields to `str | None = None` rather than `str = "default"`.
