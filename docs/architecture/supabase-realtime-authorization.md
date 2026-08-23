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
