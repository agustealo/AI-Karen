import { create } from 'zustand';
import { Plugin, PluginSearchParams, PluginSearchResponse, PluginDetails, CategoryInfo, PluginUpdate } from '@/types/plugin';
import pluginStoreService from '@/lib/PluginStoreService';

interface PluginStoreState {
  plugins: Plugin[];
  installedPlugins: Plugin[];
  installedPage: number;
  installedSearchResponse: PluginSearchResponse | null;
  installedLoading: boolean;
  installedError: string | null;
  loading: boolean;
  error: string | null;
  searchParams: PluginSearchParams;
  searchResponse: PluginSearchResponse | null;
  selectedPlugin: PluginDetails | null;
  detailsLoading: boolean;
  detailsError: string | null;
  categories: CategoryInfo[];
  trendingPlugins: Plugin[];
  trendingStatus: 'idle' | 'loading' | 'available' | 'unavailable' | 'error';
  trendingError: string | null;
  updates: PluginUpdate[];
  installingPlugins: Set<string>;
  
  setSearchParams: (params: Partial<PluginSearchParams>) => void;
  searchPlugins: () => Promise<void>;
  loadInstalled: (page?: number) => Promise<void>;
  refreshPlugins: () => Promise<void>;
  getPluginDetails: (pluginId: string) => Promise<void>;
  installPlugin: (pluginId: string, version?: string) => Promise<void>;
  disablePlugin: (pluginId: string) => Promise<void>;
  loadCategories: () => Promise<void>;
  loadTrending: () => Promise<void>;
  loadUpdates: (installedPluginIds?: string[]) => Promise<void>;
  clearSelectedPlugin: () => void;
  clearError: () => void;
}

let latestPluginSearchRequestId = 0;
let latestInstalledSearchRequestId = 0;
let latestPluginDetailsRequestId = 0;

export const usePluginStore = create<PluginStoreState>((set, get) => ({
  plugins: [],
  installedPlugins: [],
  installedPage: 1,
  installedSearchResponse: null,
  installedLoading: false,
  installedError: null,
  loading: false,
  error: null,
  searchParams: {
    page: 1,
    per_page: 20,
    sort_by: 'popularity',
  },
  searchResponse: null,
  selectedPlugin: null,
  detailsLoading: false,
  detailsError: null,
  categories: [],
  trendingPlugins: [],
  trendingStatus: 'idle',
  trendingError: null,
  updates: [],
  installingPlugins: new Set(),

  setSearchParams: (params: Partial<PluginSearchParams>) => {
    set((state) => ({
      searchParams: { ...state.searchParams, ...params },
    }));
  },

  searchPlugins: async () => {
    const requestId = ++latestPluginSearchRequestId;
    const params = { ...get().searchParams };
    set({ loading: true, error: null });
    try {
      const response = await pluginStoreService.searchPlugins(params);
      if (requestId !== latestPluginSearchRequestId) return;
      set({
        plugins: response.plugins,
        searchResponse: response,
        loading: false,
      });
    } catch (error) {
      if (requestId !== latestPluginSearchRequestId) return;
      // Never allow a stale failure to erase a newer successful response.
      set({
        plugins: [],
        searchResponse: null,
        error: error instanceof Error ? error.message : 'Failed to search plugins',
        loading: false,
      });
    }
  },

  loadInstalled: async (page?: number) => {
    const requestedPage = page ?? get().installedPage;
    const requestId = ++latestInstalledSearchRequestId;
    set({ installedLoading: true, installedError: null, installedPage: requestedPage });
    try {
      const response = await pluginStoreService.searchPlugins({
        page: requestedPage,
        per_page: 20,
        sort_by: 'name',
        installed_only: true,
      });
      if (requestId !== latestInstalledSearchRequestId) return;
      if (response.plugins.some((plugin) => plugin.status !== 'installed')) {
        throw new Error('Installed plugin catalog returned invalid lifecycle data.');
      }
      // Removing the last item on a later page must not make the entire
      // installed catalog appear empty while earlier pages still exist.
      if (
        response.total > 0 &&
        response.plugins.length === 0 &&
        requestedPage > Math.max(1, response.total_pages)
      ) {
        await get().loadInstalled(Math.max(1, response.total_pages));
        return;
      }
      if (response.total > 0 && response.plugins.length === 0) {
        throw new Error('Installed plugin catalog returned an inconsistent empty page.');
      }
      set({
        installedPlugins: response.plugins,
        installedSearchResponse: response,
        installedLoading: false,
      });
    } catch (cause) {
      if (requestId !== latestInstalledSearchRequestId) return;
      set({
        installedPlugins: [],
        installedSearchResponse: null,
        installedLoading: false,
        installedError: cause instanceof Error ? cause.message : 'Failed to load installed plugins',
      });
    }
  },

  refreshPlugins: async () => {
    await get().searchPlugins();
    const refreshError = get().error;
    await get().loadInstalled();
    const installedError = get().installedError;
    // Both browse and installed views must read back from the authoritative
    // catalog. A partial refresh must never present an unverified success.
    if (refreshError || installedError) {
      throw new Error(refreshError || installedError || 'Plugin catalog refresh failed.');
    }
  },

  getPluginDetails: async (pluginId: string) => {
    const requestId = ++latestPluginDetailsRequestId;
    set({ selectedPlugin: null, detailsLoading: true, detailsError: null });
    try {
      const details = await pluginStoreService.getPluginDetails(pluginId);
      if (requestId !== latestPluginDetailsRequestId) return;
      if (!details?.plugin || details.plugin.id !== pluginId) {
        throw new Error('Plugin details returned an invalid or mismatched plugin.');
      }
      set({ selectedPlugin: details, detailsLoading: false });
    } catch (cause) {
      if (requestId !== latestPluginDetailsRequestId) return;
      set({
        selectedPlugin: null,
        detailsLoading: false,
        detailsError: cause instanceof Error ? cause.message : 'Failed to get plugin details',
      });
    }
  },

  installPlugin: async (pluginId: string, version?: string) => {
    set((state) => ({
      installingPlugins: new Set([...state.installingPlugins, pluginId]),
      error: null,
    }));

    try {
      await pluginStoreService.installPlugin({ plugin_id: pluginId, version });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Failed to install plugin';
      set({ error: message });
      throw new Error(message);
    } finally {
      set((state) => {
        const installingPlugins = new Set(state.installingPlugins);
        installingPlugins.delete(pluginId);
        return { installingPlugins };
      });
    }

    // The package operation succeeded. A read-back failure must never be
    // mislabeled as an installation failure or presented as verified UI state.
    await get().searchPlugins();
    const refreshError = get().error;
    await get().loadInstalled();
    const installedError = get().installedError;
    if (refreshError || installedError) {
      throw new Error(
        'Plugin installation request succeeded, but the plugin list could not be refreshed: ' +
          (refreshError || installedError),
      );
    }
  },

  disablePlugin: async (pluginId: string) => {
    set((state) => ({
      installingPlugins: new Set([...state.installingPlugins, pluginId]),
      error: null,
    }));

    try {
      await pluginStoreService.disablePlugin(pluginId);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Failed to disable plugin';
      set({ error: message });
      throw new Error(message);
    } finally {
      set((state) => {
        const installingPlugins = new Set(state.installingPlugins);
        installingPlugins.delete(pluginId);
        return { installingPlugins };
      });
    }

    await get().searchPlugins();
    const refreshError = get().error;
    await get().loadInstalled();
    const installedError = get().installedError;
    if (refreshError || installedError) {
      throw new Error(
        'Plugin disable request succeeded, but the plugin list could not be refreshed: ' +
          (refreshError || installedError),
      );
    }
  },

  loadCategories: async () => {
    try {
      const categories = await pluginStoreService.getCategories();
      if (!Array.isArray(categories)) {
        throw new Error('Plugin categories response must be an array.');
      }
      set({ categories });
    } catch (error) {
      set({ categories: [], error: error instanceof Error ? error.message : 'Failed to load plugin categories' });
    }
  },

  loadTrending: async () => {
    set({ trendingStatus: 'loading', trendingError: null });
    try {
      const trending = await pluginStoreService.getTrendingPlugins();
      set({ trendingPlugins: trending, trendingStatus: 'available', trendingError: null });
    } catch (error) {
      const unavailable = error instanceof Error &&
        'status' in error && error.status === 501;
      set({
        trendingPlugins: [],
        trendingStatus: unavailable ? 'unavailable' : 'error',
        trendingError: unavailable
          ? 'Trending recommendations are not configured on this marketplace.'
          : error instanceof Error ? error.message : 'Trending plugins could not be loaded.',
      });
    }
  },

  loadUpdates: async (installedPluginIds?: string[]) => {
    try {
      const updates = await pluginStoreService.getUpdates(installedPluginIds);
      set({ updates });
    } catch (error) {
      console.error('Failed to load updates:', error);
    }
  },

  clearSelectedPlugin: () => {
    ++latestPluginDetailsRequestId;
    set({ selectedPlugin: null, detailsLoading: false, detailsError: null });
  },

  clearError: () => {
    set({ error: null });
  },
}));
