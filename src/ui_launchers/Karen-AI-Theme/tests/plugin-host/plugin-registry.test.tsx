import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { PluginRegistryProvider, usePluginRegistry, usePluginHealth, setPluginMountState, setPluginInstanceState } from '../../src/plugin_host/registry';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';

// Mock fetch for API calls
global.fetch = vi.fn() as unknown as Mock;
const mockedFetch = vi.mocked(fetch);

// Mock authentication
const auth = vi.hoisted(() => ({ user: { user_id: 'test-user', tenant_id: 'test-tenant', roles: ['user', 'admin'], permissions: [] as string[] }, isLoading: false }));
vi.mock('@/lib/useAuth', () => ({ useAuth: () => auth }));

// Both the legacy default import and the canonical named import must use
// the same controlled HTTP mock. Production registry uses the named export.
const mockGet = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
  default: { get: mockGet },
  apiClient: { get: mockGet },
}));
import apiClient from '@/lib/api';

describe('Plugin Registry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('projects backend-declared TTS without claiming a plugin frontend or a ready model', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([{
      name: 'pocket-tts',
      status: 'enabled',
      version: '1.0.0',
      display_name: 'Pocket TTS',
      capabilities: {
        provides_ui: false,
        voice_modality: { version: '1.0.0', modalities: ['tts'] },
      },
      rbac: { allowed_roles: ['user', 'admin'] },
    }]);

    const { result } = renderHook(() => usePluginRegistry(), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const entry = result.current.getPlugin('pocket-tts');
    expect(entry?.supportsVoiceOutput).toBe(true);
    expect(entry?.has_gui).toBe(false);
    expect(entry?.rawStatus).toBe('enabled');
  });

  it('fails closed on unsupported voice modality versions', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([{
      name: 'future-voice',
      status: 'enabled',
      version: '1.0.0',
      capabilities: {
        provides_ui: false,
        voice_modality: { version: '2.0.0', modalities: ['tts'] },
      },
    }]);
    const { result } = renderHook(() => usePluginRegistry(), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.getPlugin('future-voice')?.supportsVoiceOutput).toBe(false);
  });

  it('should provide plugin health status', () => {
    const { result } = renderHook(() => usePluginHealth('weather-query'), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children)
    });

    expect(result.current.pluginId).toBe('weather-query');
    expect(result.current.frontendMountState).toBe('idle');
  });

  it('should update plugin health status', () => {
    const { result } = renderHook(() => usePluginHealth('weather-query'), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children)
    });

    act(() => {
      setPluginMountState('weather-query', 'mounted');
    });
    expect(result.current.frontendMountState).toBe('mounted');
    act(() => setPluginMountState('weather-query', 'idle'));
  });
});

describe('Concurrent plugin lifecycle observations', () => {
  it('retains another mount, reports errors and reacts without manual rerender', () => {
    const id = 'file-explorer';
    const dashboard = Symbol('dashboard');
    const composer = Symbol('composer');
    const { result } = renderHook(() => usePluginHealth(id), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children),
    });
    try {
      act(() => setPluginInstanceState(id, dashboard, 'mounted'));
      act(() => setPluginInstanceState(id, composer, 'loading'));
      expect(result.current.frontendMountState).toBe('mounted');
      act(() => setPluginInstanceState(id, composer, 'error', 'Render failed'));
      expect(result.current.frontendMountState).toBe('error');
      expect(result.current.errorMessage).toBe('Render failed');
      act(() => setPluginInstanceState(id, composer, 'mounted'));
      expect(result.current.frontendMountState).toBe('mounted');
      expect(result.current.errorMessage).toBeUndefined();
      act(() => setPluginInstanceState(id, composer, 'idle'));
      expect(result.current.frontendMountState).toBe('mounted');
      act(() => setPluginInstanceState(id, dashboard, 'idle'));
      expect(result.current.frontendMountState).toBe('idle');
    } finally {
      act(() => {
        setPluginInstanceState(id, dashboard, 'idle');
        setPluginInstanceState(id, composer, 'idle');
      });
    }
  });
});


describe('Verified plugin UI eligibility', () => {
  it('removes prior principal eligibility immediately during role change and denies unlisted roles', async () => {
    const entry = { name: 'file-explorer', status: 'enabled', version: '1.0.0', capabilities: { provides_ui: true }, rbac: { allowed_roles: ['admin'] } };
    auth.user.roles = ['admin'];
    mockGet.mockReset().mockResolvedValue([entry]);
    const view = renderHook(() => usePluginRegistry(), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children),
    });
    try {
      await waitFor(() => expect(view.result.current.getPluginsWithUI().map(p => p.id)).toEqual(['file-explorer']));
      auth.user.roles = ['user'];
      view.rerender();
      expect(view.result.current.getPluginsWithUI()).toEqual([]);
      await waitFor(() => expect(view.result.current.loading).toBe(false));
      expect(view.result.current.getPluginsWithUI()).toEqual([]);
    } finally {
      view.unmount();
      auth.user.roles = ['user', 'admin'];
    }
  });
});
