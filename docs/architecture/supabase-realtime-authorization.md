# Realtime Authorization Specification

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Design
**Owner:** Security + Platform Team

---

## 1. Objective

Specify exact policies required later for `realtime.messages` without modifying live migration files.

## 2. Authorization Model

Channel membership requires:
- Authenticated user
- AND canonical tenant membership
- AND resource authorization where applicable

## 3. Conversation Channel

```text
user belongs to tenant
AND
user may access conversation
```

## 4. Execution Channel

```text
user belongs to tenant
AND
execution belongs to accessible conversation/request
```

## 5. Policy Design (Do Not Apply Yet)

```sql
CREATE POLICY realtime_messages_tenant_isolation ON realtime.messages
    FOR ALL
    USING (
        tenant_id = current_setting('app.current_tenant_id')::uuid
    );
```

## 6. Test Fixtures

See `tests/unit/core/realtime/` for authorization test fixtures.

## 7. Handoff Dependency

Active data-spine developer must apply these RLS policies after schema is ready.


## 8. KCOMM-03B/03C source boundary (candidate)

The core `RealtimeTopicFactory` owns backend topic syntax and normalization.
The database repository factory is a compatibility adapter with the original
static call signatures; it must not construct independent topic strings.
Identifiers must be UUID strings from the authenticated runtime. A syntactically
private topic does not establish ownership or authorize a subscriber.

`RealtimeSubscriber` denies admission without a trusted policy callback and
re-evaluates that callback on delivery. The callback must bind the current
authenticated session, tenant, subscription resource, event type and event
resource using canonical authorization; event payload identifiers are not
authority. The subscriber's envelope tenant check is defense in depth, not
resource authorization.

This change does not create a live transport, deploy RLS, or prove session
revocation across processes. Do not enable personal inbox push until those
gates, post-commit delivery, and browser acceptance are independently proven.
The frontend topic formatter remains a client-side syntax mirror only.
