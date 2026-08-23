# Supabase Feature Rejection Registry

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Canonical
**Owner:** Architecture Team

---

## 1. Objective

Prevent shiny-feature drift by recording features as NOT Tier-1.

## 2. Rejected Features

### Vector Buckets

- **Status:** Defer
- **Reason:** pgvector already canonical. Would create split semantic authority.

### Analytics Buckets

- **Status:** Defer
- **Reason:** Postgres/materialized views sufficient.

### Edge Functions

- **Status:** Limited exception only
- **Allowed later for small edge adapters only. Not runtime.**

### Supabase Auth

- **Status:** Separate architecture decision
- **Do not sneak into current sprint.**

### Read Replicas

- **Status:** Triggered by measured load
- **Not proactive Tier-1.**

## 3. Review Cadence

Review this registry quarterly. Any promotion to Tier-1 requires architecture review.
