# Database Webhook Governance

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Policy
**Owner:** Architecture Team

---

## 1. Allowed

External integration boundaries:
- CRM
- Billing/accounting
- External notification service
- Partner callback

## 2. Preferred Internal Path

```
Postgres -> queue -> KAREN worker
```

## 3. Forbidden

```
Postgres -> webhook -> KAREN API -> KAREN runtime
```

when a queue can do the same job.

## 4. Rationale

Webhooks bypass durable job guarantees, retry policies, and audit trails that queues provide.
