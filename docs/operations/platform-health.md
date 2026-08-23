# Supabase Platform Health Contract

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Contract
**Owner:** Platform Team

---

## 1. Components

- postgres
- storage
- realtime
- queue
- redis

## 2. Status Values

- healthy
- degraded
- unavailable
- disabled

## 3. Health Result Shape

```json
{
  "component": "realtime",
  "status": "degraded",
  "reason": "...",
  "latency_ms": 0
}
```

## 4. Implementation Note

Do not wire into current startup readiness yet if it overlaps active dev.
Provide the contract and test fixtures first.
