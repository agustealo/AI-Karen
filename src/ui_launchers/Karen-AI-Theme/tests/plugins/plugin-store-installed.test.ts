import { beforeEach, describe, expect, it, vi } from 'vitest';

import pluginStoreService from '@/lib/PluginStoreService';
import { usePluginStore } from '@/stores/PluginStore';
import type { Plugin, PluginSearchResponse } from '@/types/plugin';

vi.mock('@/lib/PluginStoreService', () => ({
  default: {
    searchPlugins: vi.fn(),
  },
}));

function plugin(id: string, status: Plugin['status']): Plugin {
  return {
    id,
    name: id,
    display_name: id,
    description: '',
    author: 'Karen',
    version: '1.0.0',
    status,
  };
}

function response(plugins: Plugin[], page = 1): PluginSearchResponse {
  return {
    plugins,
    total: plugins.length,
    page,
    per_page: 20,
    total_pages: plugins.length > 0 ? 1 : 0,
    has_next: false,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  usePluginStore.setState({
    plugins: [],
    installedPlugins: [],
    searchParams: { page: 1, per_page: 20, sort_by: 'popularity', query: 'irrelevant' },
    searchResponse: null,
    installedSearchResponse: null,
    installedPage: 1,
    installedLoading: false,
    installedError: null,
    loading: false,
    error: null,
  });
});

describe('Plugin Store installed catalog authority', () => {
  it('fetches installed plugins independently from the filtered browse page', async () => {
    const browse = response([plugin('featured', 'available')]);
    const installed = response([plugin('real-install', 'installed')]);
    vi.mocked(pluginStoreService.searchPlugins).mockImplementation(async (params) => (
      params.installed_only ? installed : browse
    ));

    await usePluginStore.getState().loadInstalled();
    await usePluginStore.getState().searchPlugins();

    const state = usePluginStore.getState();
    expect(state.plugins.map((entry) => entry.id)).toEqual(['featured']);
    expect(state.installedPlugins.map((entry) => entry.id)).toEqual(['real-install']);
    expect(pluginStoreService.searchPlugins).toHaveBeenCalledWith({
      installed_only: true,
      page: 1,
      per_page: 20,
      sort_by: 'name',
    });
  });

  it('refuses to treat a failed installed lookup as an empty successful catalog', async () => {
    vi.mocked(pluginStoreService.searchPlugins).mockRejectedValue(new Error('catalog unavailable'));

    await usePluginStore.getState().loadInstalled();

    expect(usePluginStore.getState().installedError).toBe('catalog unavailable');
    expect(usePluginStore.getState().installedSearchResponse).toBeNull();
    expect(usePluginStore.getState().installedPlugins).toEqual([]);
  });

  it('ignores malformed installed catalog states', async () => {
    vi.mocked(pluginStoreService.searchPlugins).mockResolvedValue(response([
      plugin('uninstalled', 'available'),
    ]));

    await usePluginStore.getState().loadInstalled();

    expect(usePluginStore.getState().installedError).toMatch(/invalid lifecycle data/i);
    expect(usePluginStore.getState().installedPlugins).toEqual([]);
  });

  it('paginates installed records without changing browse parameters', async () => {
    vi.mocked(pluginStoreService.searchPlugins).mockResolvedValue(response([
      plugin('installed-on-page-two', 'installed'),
    ], 2));

    await usePluginStore.getState().loadInstalled(2);

    const state = usePluginStore.getState();
    expect(state.installedPage).toBe(2);
    expect(state.searchParams.query).toBe('irrelevant');
    expect(pluginStoreService.searchPlugins).toHaveBeenCalledWith({
      installed_only: true,
      page: 2,
      per_page: 20,
      sort_by: 'name',
    });
  });
});
