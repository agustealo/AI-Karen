# KCE-FREE-01: Release eligibility ledger

This file records the source audit on November 20, 2026. It is **not** a
commercial license registry, a plugin installation registry, or evidence of
end-to-end consumer acceptance.

| Canonical package | Distribution state | Reason |
| --- | --- | --- |
| `intelligent-search` | Shipped: `free_plugins/essential/` | Existing approved mirror and SHA-256 parity test |
| `time-query` | Shipped: `free_plugins/essential/` | Existing approved mirror and SHA-256 parity test |
| `file-explorer` | Not shipped | Host-issued inventory/ACL and live integration not yet verified |
| `content-intelligence` | Not shipped | Authorized file-source integration and consumer acceptance outstanding |
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
