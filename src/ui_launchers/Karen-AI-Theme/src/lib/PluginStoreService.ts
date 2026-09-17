import apiClient from './api';
import {
  PluginSearchParams,
  PluginSearchResponse,
  Plugin,
  PluginDetails,
  PluginInstallRequest,
  PluginInstallResponse,
  PluginRatingRequest,
  PluginRatingResponse,
  PluginStoreStats,
  CategoryInfo,
  PluginUpdate,
} from '@/types/plugin';

type PluginApiItem = {
  id: string;
  name: string;
  display_name?: string;
  description: string;
  author: string;
  version: string;
  status: string;
  runtime_status?: string;
  category?: string | null;
  downloads?: number | null;
  rating?: number | null;
  rating_count?: number | null;
  latest_version?: string | null;
  installed_at?: string | null;
  icon?: string;
  marketplace_url?: string;
  homepage_url?: string;
  repository_url?: string;
  documentation_url?: string | null;
  support_url?: string | null;
  license?: string | null;
  tags?: string[];
  compatibility?: Plugin['compatibility'];
  dependencies?: string[];
};

type PluginSearchApiResponse = {
  plugins: PluginApiItem[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  has_next: boolean;
};

type PluginDetailsApiResponse = {
  plugin?: PluginApiItem;
  marketplace_info?: unknown;
  analytics?: unknown;
  installed: boolean;
  update_available?: boolean | null;
};

const PLUGIN_STATUSES = new Set<Plugin['status']>([
  'installed',
  'available',
  'compatible',
  'incompatible',
]);

class PluginStoreService {
  private readonly baseUrl = '/api/store';

  async searchPlugins(params: PluginSearchParams): Promise<PluginSearchResponse> {
    const searchParams = new URLSearchParams();

    if (params.query) searchParams.append('query', params.query);
    if (params.category) searchParams.append('category', params.category);
    if (params.sort_by) searchParams.append('sort_by', params.sort_by);
    searchParams.append('page', params.page.toString());
    searchParams.append('per_page', params.per_page.toString());
    if (params.min_version) searchParams.append('min_version', params.min_version);
    if (params.max_version) searchParams.append('max_version', params.max_version);

    const response = await apiClient.get<PluginSearchApiResponse>(
      `${this.baseUrl}/search?${searchParams.toString()}`,
    );

    return {
      plugins: response.plugins.map((plugin) => this.transformPlugin(plugin)),
      total: response.total,
      page: response.page,
      per_page: response.per_page,
      total_pages: response.total_pages,
      has_next: response.has_next,
    };
  }

  private transformPlugin(plugin: PluginApiItem): Plugin {
    if (!PLUGIN_STATUSES.has(plugin.status as Plugin['status'])) {
      throw new Error(`Unsupported plugin status from backend: ${plugin.status}`);
    }

    return {
      id: plugin.id,
      name: plugin.name,
      display_name: plugin.display_name ?? plugin.name,
      description: plugin.description,
      author: plugin.author,
      version: plugin.version,
      status: plugin.status as Plugin['status'],
      runtime_status: plugin.runtime_status,
      category: plugin.category ?? undefined,
      downloads: plugin.downloads,
      rating: plugin.rating,
      rating_count: plugin.rating_count,
      latest_version: plugin.latest_version,
      installed_at: plugin.installed_at,
      icon: plugin.icon,
      marketplace_url: plugin.marketplace_url,
      homepage_url: plugin.homepage_url,
      repository_url: plugin.repository_url,
      documentation_url: plugin.documentation_url,
      support_url: plugin.support_url,
      license: plugin.license,
      tags: plugin.tags,
      compatibility: plugin.compatibility,
      dependencies: plugin.dependencies,
    };
  }

  async getPluginDetails(pluginId: string): Promise<PluginDetails> {
    const response = await apiClient.get<PluginDetailsApiResponse>(
      `${this.baseUrl}/plugins/${pluginId}`,
    );

    return {
      plugin: response.plugin ? this.transformPlugin(response.plugin) : undefined,
      marketplace_info: response.marketplace_info,
      analytics: response.analytics,
      installed: response.installed,
      update_available: response.update_available,
    };
  }

  async installPlugin(request: PluginInstallRequest): Promise<PluginInstallResponse> {
    return apiClient.post<PluginInstallResponse>(`${this.baseUrl}/install`, request);
  }

  async ratePlugin(request: PluginRatingRequest): Promise<PluginRatingResponse> {
    return apiClient.post<PluginRatingResponse>(`${this.baseUrl}/rate`, request);
  }

  async getStatistics(): Promise<PluginStoreStats> {
    return apiClient.get<PluginStoreStats>(`${this.baseUrl}/statistics`);
  }

  async getCategories(): Promise<CategoryInfo[]> {
    return apiClient.get<CategoryInfo[]>(`${this.baseUrl}/categories`);
  }

  async getTrendingPlugins(limit = 10): Promise<Plugin[]> {
    const response = await apiClient.get<PluginApiItem[]>(
      `${this.baseUrl}/trending?limit=${limit}`,
    );
    return response.map((plugin) => this.transformPlugin(plugin));
  }

  async getUpdates(installedPluginIds?: string[]): Promise<PluginUpdate[]> {
    let url = `${this.baseUrl}/updates`;
    if (installedPluginIds && installedPluginIds.length > 0) {
      const params = new URLSearchParams();
      installedPluginIds.forEach((id) => params.append('plugin_ids', id));
      url += `?${params.toString()}`;
    }
    return apiClient.get<PluginUpdate[]>(url);
  }
}

export const pluginStoreService = new PluginStoreService();
export default pluginStoreService;
