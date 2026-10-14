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
  updates: [],
  installingPlugins: new Set(),

  setSearchParams: (params: Partial<PluginSearchParams>) => {
    set((state) => ({
      searchParams: { ...state.searchParams, ...params },
    }));
  },

  searchPlugins: async () => {
    set({ loading: true, error: null });
    try {
      const response = await pluginStoreService.searchPlugins(get().searchParams);
      set({
        plugins: response.plugins,
        searchResponse: response,
        loading: false,
      });
    } catch (error) {
      set({
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
    }));

    try {
      await pluginStoreService.installPlugin({ plugin_id: pluginId, version });
      set((state) => {
        const newInstalling = new Set(state.installingPlugins);
        newInstalling.delete(pluginId);
        return { installingPlugins: newInstalling };
      });
      await get().searchPlugins();
    } catch (error) {
      set((state) => {
        const newInstalling = new Set(state.installingPlugins);
        newInstalling.delete(pluginId);
        return {
          error: error instanceof Error ? error.message : 'Failed to install plugin',
          installingPlugins: newInstalling,
        };
      });
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
      set({
        categories: [],
        error: error instanceof Error ? error.message : 'Failed to load plugin categories',
      });
    }
  },

  loadTrending: async () => {
    try {
      const trending = await pluginStoreService.getTrendingPlugins();
      if (!Array.isArray(trending)) {
        throw new Error('Trending plugins response must be an array.');
      }
      set({ trendingPlugins: trending });
    } catch (error) {
      set({
        trendingPlugins: [],
        error: error instanceof Error ? error.message : 'Failed to load trending plugins',
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
