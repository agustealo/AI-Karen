import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { PluginRegistryProvider, usePluginRegistry, usePluginHealth, setPluginMountState } from '../../src/plugin_host/registry';
import { renderHook, act } from '@testing-library/react';
import React from 'react';

// Mock fetch for API calls
global.fetch = vi.fn() as unknown as Mock;
const mockedFetch = vi.mocked(fetch);

// Mock authentication
vi.mock('@/lib/useAuth', () => ({
  useAuth: () => ({ user: { id: 'test-user', roles: ['user', 'admin'] } })
}));

// Mock apiClient to avoid actual network calls
vi.mock('@/lib/api', () => ({
  default: {
    get: vi.fn()
  }
}));
import apiClient from '@/lib/api';

describe('Plugin Registry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should provide plugin health status', () => {
    // This will use the mock require.context from setup.ts
    const { result } = renderHook(() => usePluginHealth('weather-query'), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children)
    });
    
    expect(result.current.pluginId).toBe('weather-query');
    expect(result.current.frontendMountState).toBe('loading');
  });

  it('should update plugin health status', async () => {
    const { result } = renderHook(() => usePluginHealth('weather-query'), {
      wrapper: ({ children }) => React.createElement(PluginRegistryProvider, null, children)
    });

    act(() => {
      setPluginMountState('weather-query', 'mounted');
    });

    // Wait for the poll interval in usePluginHealth (500ms)
    await act(async () => {
      await new Promise(r => setTimeout(r, 600));
    });

    expect(result.current.frontendMountState).toBe('mounted');
  });
});