# Realtime Identity / JWT Bridge Design

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Design
**Owner:** Security + Platform Team

---

## 1. Objective

Define how KAREN identity authorizes Supabase private channels without migrating KAREN auth to Supabase Auth.

## 2. Challenge

KAREN must remain auth/RBAC authority.
Supabase Realtime still needs authenticated claims.

## 3. Design Requirements

Trusted backend determines:
- user_id
- tenant_id
- roles/scopes
- expiry
- refresh behavior
- revocation behavior

Browser cannot manufacture these claims.

## 4. Token Contract

```text
issuer: karen-backend
claims:
  sub: user_id
  tenant_id: tenant_id
  roles: [role, ...]
  scope: [scope, ...]
  exp: expiry
  iat: issued_at
  jti: unique token id
```

## 5. Expiry and Refresh

Short-lived tokens (15 minutes) with backend refresh endpoint.
Revocation invalidates existing tokens immediately.

## 6. Avoid

- Two independent user identities
- Migrating KAREN auth to Supabase Auth in this sprint

## 7. Threat Model

See `tests/unit/core/realtime/` for contract tests.
