# KCOMM-03D: Legacy event queue isolation

This slice is a containment repair, not the private Communications push transport.
The legacy queue is destructive and role-scoped; users sharing a tenant and role
are not independently addressed. Do not publish personal notification content to
it. The durable Communications inbox remains the notification authority.

- Memory selection/removal holds a single queue lock.
- Redis selection/removal uses WATCH/MULTI and removes only matched list entries,
  preserving unmatched and malformed entries and existing queue keys. All WATCH
  errors fail closed without automatic retry because redis-py can report a lost
  EXEC acknowledgment as WatchError after commit. The consumer receives an
  unavailable response, not a false empty success. This is not lossless or
  exactly-once delivery; a durable receipt protocol would be needed for that.
- Explicit Redis and legacy URL-driven Redis share one implementation. Configured
  Redis failures do not silently fall back to a process-local queue.
- Unscoped administrative hook events remain enqueueable for compatibility, but
  are not available through tenant-scoped consumption. They need a separately
  audited maintenance/retention policy before any removal.
- The existing GET route retains its contract, sets no-store, and translates
  denial/outage without exposing backend exception details.

Remaining: shared-list scan and retention bounds, tenant partition/migration,
presence and collaboration principal scoping, hook authorization, exhaustive
caller audit, real multiworker Redis proof, per-user broadcast and revocation.
The existing role labels are not a replacement for canonical RBAC. No production
activation, migrations or Redis key cleanup in this slice.
