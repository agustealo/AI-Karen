# Privacy & Redaction Specification

## Purpose

Define what **must never** be placed directly into cognitive telemetry, and the sensitivity classification system governing trace data.

## Forbidden Raw Values

The following must **never** appear in cognitive telemetry:

| Category | Examples |
|---|---|
| Authentication credentials | passwords, API keys, OAuth tokens |
| Session credentials | session tokens, refresh tokens, CSRF tokens |
| Authorization data | authorization headers, bearer tokens |
| Private memory content | memory plaintext, private memory text |
| Conversation content | full conversation contents, message bodies |
| Tool secrets | tool API keys, tool credentials |
| Provider internals | provider raw payloads, provider credentials |
| Sensitive documents | document bodies, file contents |
| Cryptographic material | private keys, encryption keys |
| Personal data | PII beyond governed user_id scope |

## Reference-Only Rule

Use references rather than dumping contents:

```
memory_ref=m-182         ✓
claim_ref=claim-43       ✓
evidence_ref=e-91        ✓
decision_ref=dec-456     ✓

memory_text="..."        ✗
claim_text="..."         ✗
conversation="..."       ✗
reasoning_trace="..."    ✗
```

## Trace Sensitivity Classes

### PUBLIC_SAFE

Data safe for unrestricted use within the system.

| Attribute | Allowed |
|---|---|
| Event IDs | Yes |
| Event types | Yes |
| Cognitive stage | Yes |
| Schema version | Yes |
| Policy version | Yes |
| Reason codes | Yes |
| Status values | Yes |
| Duration values | Yes |
| Provider name | Yes |
| Model name | Yes |
| Topology type | Yes |

### INTERNAL

Data safe for internal system use but not external exposure.

| Attribute | Allowed |
|---|---|
| Memory IDs | Yes |
| Belief IDs | Yes |
| Goal IDs | Yes |
| Candidate IDs | Yes |
| Recall scores | Yes |
| Salience scores | Yes |
| Confidence values | Yes |
| Feature snapshot refs | Yes |
| Decision observation refs | Yes |

### USER_PRIVATE

Data scoped to the user that must not leak across users.

| Attribute | Allowed |
|---|---|
| User ID | Governed (same-user only) |
| Session ID | Governed (same-user only) |
| Conversation ID | Governed (same-user only) |
| User preferences | Governed (same-user only) |
| User model refs | Governed (same-user only) |

### SECURITY_SENSITIVE

Data that could aid attackers if exposed.

| Attribute | Allowed |
|---|---|
| Tenant ID | Governed (same-tenant only) |
| Policy decision details | Governed (audit only) |
| Verification requirements | Governed (audit only) |
| Security event details | Governed (audit only) |

### SECRET

Data that must never appear in telemetry.

| Attribute | Allowed |
|---|---|
| Passwords | Never |
| API keys | Never |
| OAuth tokens | Never |
| Credentials | Never |
| Private memory text | Never |
| Full conversation contents | Never |
| Tool secrets | Never |
| Authorization headers | Never |
| Sensitive document bodies | Never |
| Provider raw payloads | Never |
| Private keys | Never |
| Session tokens | Never |

## Attribute Allowance Matrix

| Attribute | PUBLIC_SAFE | INTERNAL | USER_PRIVATE | SECURITY_SENSITIVE | SECRET |
|---|:---:|:---:|:---:|:---:|:---:|
| event_id | ✓ | ✓ | ✓ | ✓ | ✓ |
| event_type | ✓ | ✓ | ✓ | ✓ | ✓ |
| correlation_id | ✓ | ✓ | ✓ | ✓ | ✓ |
| cognitive_stage | ✓ | ✓ | ✓ | ✓ | ✓ |
| schema_version | ✓ | ✓ | ✓ | ✓ | ✓ |
| policy_version | ✓ | ✓ | ✓ | ✓ | ✓ |
| reason_codes | ✓ | ✓ | ✓ | ✓ | ✓ |
| status | ✓ | ✓ | ✓ | ✓ | ✓ |
| duration_ms | ✓ | ✓ | ✓ | ✓ | ✓ |
| provider_name | ✓ | ✓ | ✓ | ✓ | ✓ |
| model_name | ✓ | ✓ | ✓ | ✓ | ✓ |
| memory_ref | | ✓ | ✓ | ✓ | ✓ |
| belief_ref | | ✓ | ✓ | ✓ | ✓ |
| goal_ref | | ✓ | ✓ | ✓ | ✓ |
| candidate_id | | ✓ | ✓ | ✓ | ✓ |
| recall_score | | ✓ | ✓ | ✓ | ✓ |
| salience_score | | ✓ | ✓ | ✓ | ✓ |
| confidence | | ✓ | ✓ | ✓ | ✓ |
| belief confidence | | ✓ | ✓ | ✓ | ✓ |
| user_id | | | ✓ | ✓ | ✓ |
| session_id | | | ✓ | ✓ | ✓ |
| conversation_id | | | ✓ | ✓ | ✓ |
| tenant_id | | | | ✓ | ✓ |
| memory_text | ✗ | ✗ | ✗ | ✗ | ✗ |
| claim_text | ✗ | ✗ | ✗ | ✗ | ✗ |
| conversation_content | ✗ | ✗ | ✗ | ✗ | ✗ |
| reasoning_trace | ✗ | ✗ | ✗ | ✗ | ✗ |
| password | ✗ | ✗ | ✗ | ✗ | ✗ |
| api_key | ✗ | ✗ | ✗ | ✗ | ✗ |
| oauth_token | ✗ | ✗ | ✗ | ✗ | ✗ |
| credential | ✗ | ✗ | ✗ | ✗ | ✗ |
| private_key | ✗ | ✗ | ✗ | ✗ | ✗ |
| session_token | ✗ | ✗ | ✗ | ✗ | ✗ |

## Redaction Rules

### At Emission

All cognitive telemetry must be redacted at emission time using the existing redaction subsystem (`core/observability/redaction.py`).

### At Rest

Stored traces must maintain redaction. No raw secrets in storage.

### At Query

Query interfaces must enforce sensitivity class access controls.

## Deletion-Aware Tracing

### Reference Survival

If memory `m123` is deleted:

- Historical telemetry **may** retain `memory_ref=m-123` where governance permits
- Historical telemetry **must not** retain deleted semantic content

### Content Deletion

When content is deleted:

1. All references to the content remain (for lineage)
2. The content itself is purged from telemetry stores
3. No content reconstruction from telemetry is possible

### Anti-Shadow-Database

Deletion must not create a loophole where an observability backend becomes a shadow memory database.

Rules:

1. Telemetry stores must honor deletion requests for referenced content
2. Telemetry must not be queryable as a memory substitute
3. Retention policies must apply to telemetry as well as memory
4. Cross-referencing telemetry to reconstruct deleted content is prohibited

## Relationship to Existing Redaction

This specification extends existing redaction (`core/observability/redaction.py`, `core/logging/redaction.py`) with cognitive-stage awareness.

| Existing | Cognitive Extension |
|---|---|
| `redact_text()` | Applied to all cognitive event `safe_attributes` |
| `redact_data()` | Applied to all cognitive telemetry payloads |
| `_SENSITIVE_KEYS` | Extended with cognitive-specific sensitive keys |
| `sanitize_secrets()` | Applied at cognitive record build time |

## Cognitive-Specific Sensitive Keys

In addition to existing sensitive keys, cognitive telemetry must treat these as sensitive:

- `memory_text`
- `claim_text`
- `belief_text`
- `reasoning_trace`
- `private_reasoning`
- `internal_monologue`
- `chain_of_thought`
- `conversation_content`
- `message_body`
- `document_body`
- `provider_payload`
- `tool_result_content`
