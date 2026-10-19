import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeRuntimeProviderCatalogResponse } from '@/lib/model-runtime-inventory';
import { useModelSettings } from '@/components/chat/const/modelSettings';

const apiMocks = vi.hoisted(() => ({ put: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiClient: apiMocks }));

const inventory = normalizeRuntimeProviderCatalogResponse({
  default_provider: 'ollama',
  default_model: 'installed:latest',
  providers: [{
    id: 'ollama',
    label: 'Ollama',
    category: 'local',
    enabled: true,
    configured: true,
    healthy: true,
    selected_model: 'installed:latest',
    models: [{ id: 'installed:latest', label: 'Installed model', available: true }],
  }],
});

describe('personal chat model preference', () => {
  beforeEach(() => vi.clearAllMocks());

  it('refuses an unavailable model without attempting to save global or personal settings', async () => {
    const { result } = renderHook(() => useModelSettings());
    const setProvider = vi.fn();
    const setModel = vi.fn();
    const setLoading = vi.fn();
    const toast = vi.fn();

    await act(async () => {
      await result.current.applyModelSelection(
        'ollama', 'removed:latest', inventory, vi.fn(), setProvider, setModel, setLoading, toast,
      );
    });

    expect(apiMocks.put).not.toHaveBeenCalled();
    expect(setProvider).not.toHaveBeenCalled();
    expect(setModel).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Model unavailable', variant: 'destructive',
    }));
  });

  it('saves an authorized model only to the personal model-selection endpoint', async () => {
    apiMocks.put.mockResolvedValueOnce({
      status: 'ok',
      model_selection: { provider: 'ollama', model: 'installed:latest' },
    });
    const { result } = renderHook(() => useModelSettings());
    const setProvider = vi.fn();
    const setModel = vi.fn();
    const setLoading = vi.fn();
    const toast = vi.fn();

    await act(async () => {
      await result.current.applyModelSelection(
        'ollama', 'installed:latest', inventory, vi.fn(), setProvider, setModel, setLoading, toast,
      );
    });

    expect(apiMocks.put).toHaveBeenCalledExactlyOnceWith('/api/settings/model-selection', {
      provider: 'ollama',
      model: 'installed:latest',
    });
    expect(setProvider).toHaveBeenCalledWith('ollama');
    expect(setModel).toHaveBeenCalledWith('installed:latest');
  });
});
