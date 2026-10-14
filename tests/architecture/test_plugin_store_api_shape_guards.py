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
