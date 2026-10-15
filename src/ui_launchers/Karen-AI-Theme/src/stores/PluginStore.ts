import { create } from 'zustand';
import { Plugin, PluginSearchParams, PluginSearchResponse, PluginDetails, CategoryInfo, PluginUpdate } from '@/types/plugin';
import pluginStoreService from '@/lib/PluginStoreService';

interface PluginStoreState {
  plugins: Plugin[];
  loading: boolean;
  error: string | null;
  searchParams: PluginSearchParams;
  searchResponse: PluginSearchResponse | null;
  selectedPlugin: PluginDetails | null;
  categories: CategoryInfo[];
  trendingPlugins: Plugin[];
  trendingStatus: 'idle' | 'loading' | 'available' | 'unavailable' | 'error';
  trendingError: string | null;
  updates: PluginUpdate[];
  installingPlugins: Set<string>;
  
  setSearchParams: (params: Partial<PluginSearchParams>) => void;
  searchPlugins: () => Promise<void>;
  refreshPlugins: () => Promise<void>;
  getPluginDetails: (pluginId: string) => Promise<void>;
  installPlugin: (pluginId: string, version?: string) => Promise<void>;
  loadCategories: () => Promise<void>;
  loadTrending: () => Promise<void>;
  loadUpdates: (installedPluginIds?: string[]) => Promise<void>;
  clearSelectedPlugin: () => void;
  clearError: () => void;
}

let latestPluginSearchRequestId = 0;

export const usePluginStore = create<PluginStoreState>((set, get) => ({
  plugins: [],
  loading: false,
  error: null,
  searchParams: {
    page: 1,
    per_page: 20,
    sort_by: 'popularity',
  },
  searchResponse: null,
  selectedPlugin: null,
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

  refreshPlugins: async () => {
    await get().searchPlugins();
    // searchPlugins preserves its existing UI error state, but lifecycle
    // callers must not announce a verified refresh when retrieval failed.
    const refreshError = get().error;
    if (refreshError) {
      throw new Error(refreshError);
    }
  },

  getPluginDetails: async (pluginId: string) => {
    set({ loading: true, error: null });
    try {
      const details = await pluginStoreService.getPluginDetails(pluginId);
      set({
        selectedPlugin: details,
        loading: false,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to get plugin details',
        loading: false,
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
    if (refreshError) {
      throw new Error(
        'Plugin installation request succeeded, but the plugin list could not be refreshed: ' +
          refreshError,
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
    set({ selectedPlugin: null });
  },

  clearError: () => {
    set({ error: null });
  },
}));
