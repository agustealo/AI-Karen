# Shipped free plugin files

This directory is **storage only** for free plugins distributed with Karen.

- `essential/`: shipped essential plugin packages (currently Intelligent Search and Time Query)
- `premium/`: shipped premium-category plugin packages, when available

This directory is not an installer, marketplace, plugin registry, runtime source of truth, or automatic activation mechanism.

Users choose the plugins they want, then **upload and install them manually through Karen's existing Plugin UI**. That UI must use the existing governed backend installation path, including permission checks, validation, audit, and reporting of actual installation state. Merely storing a plugin here does not install, enable, register, or mount it.

The existing `src/ai_karen_engine/extensions/plugins/` directories are retained for compatibility until the canonical runtime and Plugin UI migration is verified. Do not delete active plugin runtime files as part of this storage-only change.
