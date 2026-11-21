# Shipped free plugin files

This directory is **storage only** for free plugins distributed with Karen.

- `essential/`: shipped essential plugin packages (currently Intelligent Search and Time Query)
- `premium/`: shipped premium-category plugin packages, when available

This directory is not an installer, marketplace, plugin registry, runtime source of truth, or automatic activation mechanism.

Users choose the plugins they want, then **upload and install them manually through Karen's existing Plugin UI**. That UI must use the existing governed backend installation path, including permission checks, validation, audit, and reporting of actual installation state. Merely storing a plugin here does not install, enable, register, or mount it.

The existing `src/ai_karen_engine/extensions/plugins/` directories are retained for compatibility until the canonical runtime and Plugin UI migration is verified. Do not delete active plugin runtime files as part of this storage-only change.


## Release-mirror invariant

The canonical preinstalled packages under `src/ai_karen_engine/extensions/plugins/<id>/` are the only source implementation. Once a plugin is approved for distribution, its `free_plugins/essential/<id>/` directory is a **byte-for-byte release mirror** of that canonical package, including manifest, handlers, prompts, and UI resources. Shipping a stale or independently edited copy is prohibited.

`tests/architecture/test_free_plugin_release_mirrors.py` enforces package file-set, SHA-256, and manifest equality for every currently mirrored essential package in the existing Main Quality gate. A package update must update the canonical source first, then copy the complete reviewed source into the free folder and pass the gate. Do not fix runtime behavior in the free mirror.

Only proven ship-ready plugins may be copied. The preinstalled `whatsapp-cloud`, `telegram-bot`, and `zulip-cloud` communication adapters are **not** automatically publishable as free packages merely because the backend catalog discovers them. They require governed tenant activation, independent provider/live delivery acceptance, exact-head CI, signed-in UI proof, and a reviewed release decision before mirroring. Keep backend-only channel transports disabled to generic plugin execution.

This distribution parity rule does not validate tenant credentials, remote provider health, or production release readiness. It guarantees the shipped copy is identical to the approved canonical source, not that an unproven source is approved.

## Release ledger and synchronization

See [KCE-FREE-01 release eligibility ledger](RELEASE_ELIGIBILITY.md) for the current approved mirrors and pending candidates. Verify existing release copies with `python scripts/sync_free_plugin_release_mirrors.py`; pass `--sync` to refresh existing mirrors after canonical-source review. This command never publishes a new package or activates a plugin.
