import { beforeEach, describe, expect, it, vi } from 'vitest';

import apiClient from '@/lib/api';
import pluginStoreService from '@/lib/PluginStoreService';

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() },
}));

beforeEach(() => {
  vi.resetAllMocks();
});

describe('Plugin Store uploaded-code quarantine', () => {
  it('preserves backend isolation denial through the catalog adapter', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      plugins: [{
        id: 'manual-upload',
        name: 'manual-upload',
        display_name: 'Manual Upload',
        description: '',
        author: 'User',
        version: '1.0.0',
        status: 'installed',
        runtime_status: 'disabled',
        activation_blocked_reason: 'isolated_runtime_required',
      }],
      total: 1,
      page: 1,
      per_page: 20,
      total_pages: 1,
      has_next: false,
    });

    const catalog = await pluginStoreService.searchPlugins({
      page: 1,
      per_page: 20,
      sort_by: 'name',
    });

    expect(catalog.plugins).toHaveLength(1);
    expect(catalog.plugins[0].status).toBe('installed');
    expect(catalog.plugins[0].runtime_status).toBe('disabled');
    expect(catalog.plugins[0].activation_blocked_reason).toBe('isolated_runtime_required');
  });

  it('preserves quarantine reason in the details response', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      plugin: {
        id: 'manual-upload',
        name: 'manual-upload',
        display_name: 'Manual Upload',
        description: '',
        author: 'User',
        version: '1.0.0',
        status: 'installed',
        runtime_status: 'disabled',
        activation_blocked_reason: 'isolated_runtime_required',
      },
      installed: true,
      update_available: null,
    });

    const details = await pluginStoreService.getPluginDetails('manual-upload');

    expect(details.installed).toBe(true);
    expect(details.plugin?.activation_blocked_reason).toBe('isolated_runtime_required');
  });
});
