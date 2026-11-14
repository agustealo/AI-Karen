"""Prevent Plugin Store UI crashes when remote arrays are missing or malformed."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src"
SERVICE = ROOT / "lib/PluginStoreService.ts"
STORE = ROOT / "stores/PluginStore.ts"
PAGE = ROOT / "components/plugins/PluginStorePage.tsx"


def test_service_rejects_malformed_search_and_trending_payloads() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "Array.isArray(response.plugins)" in text
    assert "Trending plugins endpoint returned an invalid response." in text
    assert "Plugin categories endpoint returned an invalid response." in text
    assert "if (!Array.isArray(response))" in text


def test_store_and_page_never_assume_categories_loaded() -> None:
    store = STORE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    assert "categories: []" in store
    assert "trendingPlugins: []" in store
    assert "Array.isArray(categories) ? categories : []" in page
    assert "safeCategories.length > 0" in page
    assert "safeCategories.find(" in page


def test_install_failures_reach_page_and_refresh_failures_are_distinguished() -> None:
    store = STORE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    assert "throw new Error(message);" in store
    assert "Plugin installation request succeeded, but the plugin list could not be refreshed:" in store
    assert "await get().searchPlugins();" in store
    assert "setOperationError(getErrorMessage(installError));" in page


def test_plugin_store_refresh_catches_rejections_for_visible_error() -> None:
    page = PAGE.read_text(encoding="utf-8")
    assert "const handleRefresh = useCallback(async () => {" in page
    assert "await refreshPlugins();" in page
    assert "setOperationError(getErrorMessage(cause));" in page
    assert "void refreshPlugins();" not in page



def test_failed_search_does_not_reuse_previous_plugin_list() -> None:
    store = STORE.read_text(encoding="utf-8")
    search_action = store.split("  searchPlugins: async () => {", 1)[1].split(
        "  refreshPlugins: async () => {", 1
    )[0]
    assert "plugins: []" in search_action
    assert "searchResponse: null" in search_action
    assert "Failed to search plugins" in search_action


def test_plugin_search_ignores_superseded_success_and_failure() -> None:
    store = STORE.read_text(encoding="utf-8")
    action = store.split("  searchPlugins: async () => {", 1)[1].split(
        "  refreshPlugins: async () => {", 1
    )[0]
    assert "const requestId = ++latestPluginSearchRequestId;" in action
    assert "const params = { ...get().searchParams };" in action
    assert action.count("if (requestId !== latestPluginSearchRequestId) return;") == 2
    assert "plugins: response.plugins" in action
    assert "plugins: []" in action


def test_plugin_store_disabled_lifecycle_actions_use_real_backend_paths() -> None:
    card = (ROOT / "components/plugins/PluginCard.tsx").read_text(encoding="utf-8")
    badge = (ROOT / "components/plugins/PluginStatusBadge.tsx").read_text(encoding="utf-8")
    grid = (ROOT / "components/plugins/PluginGrid.tsx").read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    state = STORE.read_text(encoding="utf-8")

    assert "plugin.runtime_status === 'disabled' ? 'disabled' : plugin.status" in card
    assert "plugin.status === 'available' || plugin.runtime_status === 'disabled'" in card
    assert "plugin.runtime_status === 'enabled'" in card
    assert "onDisable?.(pluginId);" in card
    assert "PluginStatus | 'disabled' | 'error'" in badge
    assert "onDisable={onDisable}" in grid
    assert page.count("onDisable={handleDisable}") == 3
    assert page.count("onInstall={handleInstall}") == 3
    assert "await disablePlugin(pluginId);" in page
    assert "`/api/plugins/${encodeURIComponent(pluginId)}/disable`" in service
    assert "await pluginStoreService.disablePlugin(pluginId);" in state
    assert "Plugin disable request succeeded, but the plugin list could not be refreshed:" in state


def test_upload_and_uninstall_use_authenticated_canonical_store_paths() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    api = (ROOT / "lib/api.ts").read_text(encoding="utf-8")

    assert "async uploadPlugin(pluginId: string, archive: File)" in service
    assert "apiClient.postFormData<" in service
    assert "`${this.baseUrl}/upload`" in service
    assert "`${this.baseUrl}/${encodeURIComponent(pluginId)}/installation`" in service
    assert "apiClient.delete<" in service
    assert "await pluginStoreService.uploadPlugin(uploadId, uploadFile)" in page
    assert "await pluginStoreService.uninstallPlugin(uninstallId)" in page
    assert "result?.success !== true || result.installed !== true || result.enabled !== false" in page
    assert "result?.success !== true || result.uninstalled !== true" in page
    assert "/api/plugins/store" not in page
    assert "await fetch(" not in page
    assert "async postFormData<T>(endpoint: string, data: FormData)" in api
    assert "if (init.body instanceof FormData)" in api
    assert "delete requestHeaders['Content-Type'];" in api


def test_installed_catalog_is_not_the_current_browse_page() -> None:
    page = PAGE.read_text(encoding="utf-8")
    state = STORE.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    types = (ROOT / "types/plugin.ts").read_text(encoding="utf-8")
    backend = (
        Path(__file__).resolve().parents[2] / "src/ai_karen_engine/api_routes/plugins/store.py"
    ).read_text(encoding="utf-8")

    assert "plugins.filter((plugin) => plugin.status === 'installed')" not in page
    assert "installedPlugins," in page
    assert "installedSearchResponse," in page
    assert "installedLoading," in page
    assert "installedError," in page
    assert "void loadInstalled();" in page
    assert "onPageChange={(page) => { void loadInstalled(page); }}" in page
    assert "installed_only: true" in state
    assert "latestInstalledSearchRequestId" in state
    assert "installedError:" in state
    assert "if (refreshError || installedError)" in state
    assert "searchParams.append('installed_only', 'true')" in service
    assert "installed_only: z.boolean().optional()" in types
    assert 'plugin["status"] == "installed"' in backend
    assert '"incompatible" if runtime_status == "error"' in backend
