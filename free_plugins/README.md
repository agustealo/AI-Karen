# Free Plugin Catalog

Plugins are **offered**, not installed automatically from this catalog.

- `essential/`: basic bundled capabilities: `intelligent-search` and `time-query`.
- `premium/`: reserved for optional free premium-tier plugin packages. Empty until vetted plugins are provided. The name does **not** imply a payment or entitlement bypass.

List local offerings:

```bash
python scripts/manage_free_plugins.py list
```

To install a package explicitly:

```bash
python scripts/manage_free_plugins.py install essential time-query
python scripts/manage_free_plugins.py install essential intelligent-search
```

The installer refuses to overwrite existing plugin directories, rejects linked package files and invalid IDs, and stages a package before publishing it. Restart Karen or refresh the canonical runtime plugin registry afterward. Installing package files alone does not automatically enable the plugin, grant permissions, mount its UI, or prove its health. Continue using existing RBAC-governed controls for activation.

**Migration note:** This first step preserves existing runtime directories in `src/ai_karen_engine/extensions/plugins/` as previously installed packages. They may already be present, in which case the manual install command correctly refuses to overwrite them. A separate loader migration and explicit governed uninstall are needed before removing those legacy copies. Do not delete the runtime directories manually.

Plugin packages in the catalog remain version-controlled originals. New catalog entries require manifest review, permission validation, license/source review, and integration tests.
