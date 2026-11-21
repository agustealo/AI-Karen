# KCE-FREE-01: Release eligibility ledger

This file records the source audit on November 20, 2026. It is **not** a
commercial license registry, a plugin installation registry, or evidence of
end-to-end consumer acceptance.

| Canonical package | Distribution state | Reason |
| --- | --- | --- |
| `intelligent-search` | Shipped: `free_plugins/essential/` | Existing approved mirror and SHA-256 parity test |
| `time-query` | Shipped: `free_plugins/essential/` | Existing approved mirror and SHA-256 parity test |
| `file-explorer` | Not shipped | Authenticated owner-inventory API and selected-file UI merged; live deployment/browser acceptance not yet certified |
| `content-intelligence` | Not shipped | Authenticated runtime source admission, owner-text API and File Explorer analysis UI merged; live browser and revocation acceptance outstanding |
| `pocket-tts` | Not shipped | Licensed model installation and real target-host acceptance outstanding |
| `telegram-bot` | Not shipped | Governed channel activation and external live delivery acceptance outstanding |
| `whatsapp-cloud` | Not shipped | Governed channel activation and external live delivery acceptance outstanding |
| `zulip-cloud` | Not shipped | Governed channel activation and external live delivery acceptance outstanding |

Additional system-extension directories `crawl4ai` and `data_connector`
are not automatically considered distributable plugin packages.

## Publishing contract

- Keep implementation source in `src/ai_karen_engine/extensions/plugins/<id>/`.
- Release copies under `free_plugins/<category>/<id>/` must be byte-identical
  to canonical source and are never automatically installed or activated.
- Run `python scripts/sync_free_plugin_release_mirrors.py` to verify every
  existing approved mirror; run with `--sync` to refresh **existing** mirrors.
- New packages require explicit manifest/license and operational acceptance,
  then an intentionally reviewed directory addition. The script will not
  manufacture an approval by creating a new package directory.
- The existing essential parity test remains authoritative for essential
  package source bytes; this cross-category guard protects future categories.
- MIT-licensed code already released under MIT retains its license rights;
  commercial offers must not retroactively revoke those rights.
- No paid services, license checks, private packages, or marketplace backends
  may be necessary to build or run the open-source core.

Pending publication decisions require separate exact-head validation and
reconciliation of existing PRs before release.

## KCE-FREE-04: Live consumer evidence and release gate

The source-level integration merged through PR #1163 (merge
`ea94ef416dea9d8db54b7f56a72aac46ea083ed9`) and PR #1167 (merge
`550ea1e2d84eff30202936988a3900fb3618fdf2`). These mergers and their
exact-head CI do **not** establish a usable deployed, authenticated product.
No successful protected live consumer-acceptance run was verified when this
ledger was updated.

The existing [protected browser workflow](../.github/workflows/karen-history-browser-acceptance.yml)
provides the `file-explorer` and `content-intelligence` dispatch scenarios.
The latter selects a genuinely owned, active supported text/code artifact and
observes the authorized analysis HTTP exchange and rendered result. It uses a
sanitized authenticated account, an independently verified immutable deployed
revision, and does not mock requests or capture private browser artifacts.

Before shipping either package, record an actual successful protected run:
its workflow/job URL, exact 40-character deployed/main SHA, reviewer,
nonsecret fixture inventory (supported MIME, actual ownership, Storage
availability and plugin enablement), and a witnessed signed-in result. Also
record negative-case source revocation, tenant isolation and revision-change
proof from live canonical PostgreSQL/Storage, plus a verified release manifest
and byte-parity result. Until all evidence is verified, retain **Not shipped**
and do not add a directory under `free_plugins/community/`.

See [the protected acceptance runbook](../docs/plugins/content-intelligence/04-live-consumer-acceptance.md).
