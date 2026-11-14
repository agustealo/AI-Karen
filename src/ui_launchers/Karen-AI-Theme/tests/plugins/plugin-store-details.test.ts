import { beforeEach, describe, expect, it, vi } from 'vitest';

import pluginStoreService from '@/lib/PluginStoreService';
import { usePluginStore } from '@/stores/PluginStore';
import type { PluginDetails } from '@/types/plugin';

vi.mock('@/lib/PluginStoreService', () => ({
  default: {
    getPluginDetails: vi.fn(),
  },
}));

const details = (id: string): PluginDetails => ({
  installed: true,
  update_available: null,
  plugin: {
    id,
    name: id,
    display_name: id,
    description: '',
    author: 'Karen',
    version: '1.0.0',
    status: 'installed',
    runtime_status: 'enabled',
  },
});

beforeEach(() => {
  vi.resetAllMocks();
  usePluginStore.setState({
    selectedPlugin: null,
    detailsLoading: false,
    detailsError: null,
    loading: false,
    error: null,
  });
});

describe('Plugin details store lifecycle', () => {
  it('loads details without blocking the browse catalog', async () => {
    let finish: (value: PluginDetails) => void = () => {
      throw new Error('Details promise not initialized');
    };
    const pending = new Promise<PluginDetails>((resolve) => {
      finish = resolve;
    });
    vi.mocked(pluginStoreService.getPluginDetails).mockReturnValue(pending);

    const task = usePluginStore.getState().getPluginDetails('alpha');
    expect(usePluginStore.getState().detailsLoading).toBe(true);
    expect(usePluginStore.getState().loading).toBe(false);

    finish(details('alpha'));
    await task;

    expect(usePluginStore.getState().selectedPlugin?.plugin?.id).toBe('alpha');
    expect(usePluginStore.getState().detailsLoading).toBe(false);
    expect(usePluginStore.getState().detailsError).toBeNull();
  });

  it('rejects mismatched plugin details instead of showing another plugin', async () => {
    vi.mocked(pluginStoreService.getPluginDetails).mockResolvedValue(details('other'));

    await usePluginStore.getState().getPluginDetails('expected');

    expect(usePluginStore.getState().selectedPlugin).toBeNull();
    expect(usePluginStore.getState().detailsError).toMatch(/mismatched plugin/);
  });

  it('preserves a visible detail failure instead of silently showing nothing', async () => {
    vi.mocked(pluginStoreService.getPluginDetails).mockRejectedValue(new Error('catalog denied'));

    await usePluginStore.getState().getPluginDetails('alpha');

    expect(usePluginStore.getState().selectedPlugin).toBeNull();
    expect(usePluginStore.getState().detailsError).toBe('catalog denied');
    expect(usePluginStore.getState().detailsLoading).toBe(false);
  });

  it('ignores a late lookup after the details modal closes', async () => {
    let finish: (value: PluginDetails) => void = () => {
      throw new Error('Details promise not initialized');
    };
    const pending = new Promise<PluginDetails>((resolve) => {
      finish = resolve;
    });
    vi.mocked(pluginStoreService.getPluginDetails).mockReturnValue(pending);

    const task = usePluginStore.getState().getPluginDetails('alpha');
    usePluginStore.getState().clearSelectedPlugin();
    finish(details('alpha'));
    await task;

    expect(usePluginStore.getState().selectedPlugin).toBeNull();
    expect(usePluginStore.getState().detailsError).toBeNull();
    expect(usePluginStore.getState().detailsLoading).toBe(false);
  });
});
