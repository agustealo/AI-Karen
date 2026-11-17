import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import PluginStorePage from '@/components/plugins/PluginStorePage';

const state = vi.hoisted(() => ({
  push: vi.fn(),
  getPlugin: vi.fn(),
  catalogLoading: false,
  catalogError: null as string | null,
  selectedPlugin: null as {
    installed: boolean;
    plugin: {
      id: string;
      name: string;
      display_name: string;
      description: string;
      version: string;
      status: 'installed';
      runtime_status: string;
      settings_available: boolean;
    };
  } | null,
  loadCategories: vi.fn(),
  searchPlugins: vi.fn(),
  loadInstalled: vi.fn(),
  loadTrending: vi.fn(),
  getPluginDetails: vi.fn(),
  clearSelectedPlugin: vi.fn(),
  setSearchParams: vi.fn(),
  refreshPlugins: vi.fn(),
  installPlugin: vi.fn(),
  enablePlugin: vi.fn(),
  disablePlugin: vi.fn(),
  clearError: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: state.push }),
}));

vi.mock('@/plugin_host/registry', () => ({
  usePluginRegistry: () => ({
    getPlugin: state.getPlugin,
    loading: state.catalogLoading,
    error: state.catalogError,
  }),
}));

vi.mock('@/stores/PluginStore', () => ({
  usePluginStore: () => ({
    plugins: [],
    installedPlugins: [],
    installedPage: 1,
    installedSearchResponse: null,
    installedLoading: false,
    installedError: null,
    loading: false,
    error: null,
    searchParams: { page: 1, per_page: 20, sort_by: 'popularity' },
    searchResponse: null,
    categories: [],
    trendingPlugins: [],
    trendingStatus: 'idle',
    trendingError: null,
    installingPlugins: new Set<string>(),
    selectedPlugin: state.selectedPlugin,
    detailsLoading: false,
    detailsError: null,
    setSearchParams: state.setSearchParams,
    searchPlugins: state.searchPlugins,
    loadInstalled: state.loadInstalled,
    refreshPlugins: state.refreshPlugins,
    installPlugin: state.installPlugin,
    enablePlugin: state.enablePlugin,
    disablePlugin: state.disablePlugin,
    loadCategories: state.loadCategories,
    loadTrending: state.loadTrending,
    getPluginDetails: state.getPluginDetails,
    clearSelectedPlugin: state.clearSelectedPlugin,
    clearError: state.clearError,
  }),
}));

vi.mock('@/lib/PluginStoreService', () => ({
  default: { uninstallPlugin: vi.fn(), uploadPlugin: vi.fn() },
}));
vi.mock('@/components/plugins/PluginGrid', () => ({
  PluginGrid: ({ onDetails }: { onDetails: (id: string) => void }) => (
    <button type="button" onClick={() => onDetails('pocket-tts')}>
      Open plugin details
    </button>
  ),
}));
vi.mock('@/components/plugins/SearchBar', () => ({
  SearchBar: () => null,
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.catalogLoading = false;
  state.catalogError = null;
  state.selectedPlugin = {
    installed: true,
    plugin: {
      id: 'pocket-tts',
      name: 'pocket-tts',
      display_name: 'Pocket TTS',
      description: 'Governed local speech',
      version: '1.0.0',
      status: 'installed',
      runtime_status: 'enabled',
      settings_available: false,
    },
  };
  state.getPlugin.mockReturnValue({
    id: 'pocket-tts',
    supportsVoiceOutput: true,
    has_gui: false,
    enabled: true,
  });
});

afterEach(cleanup);

describe('Plugin Store to governed Voice Studio navigation', () => {
  it('routes a backend-declared TTS plugin to the existing Assistant Voice settings panel', () => {
    render(<PluginStorePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Open plugin details' }));
    expect(screen.queryByRole('button', { name: 'Configure' })).toBeNull();

    fireEvent.click(screen.getByRole('button', {
      name: 'Open Voice Studio for Pocket TTS',
    }));

    expect(state.push).toHaveBeenCalledOnce();
    expect(state.push).toHaveBeenCalledWith('/dashboard?view=settings&section=voice');
    expect(state.clearSelectedPlugin).toHaveBeenCalledOnce();
    expect(state.getPlugin).toHaveBeenCalledWith('pocket-tts');
  });

  it("opens the exact Pocket TTS user workspace from verified plugin-store details", () => {
    render(<PluginStorePage />);
    fireEvent.click(screen.getByRole("button", { name: "Open plugin details" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Pocket TTS workspace" }));
    expect(state.push).toHaveBeenCalledOnce();
    expect(state.push).toHaveBeenCalledWith("/dashboard?view=pocket-tts");
    expect(state.clearSelectedPlugin).toHaveBeenCalledOnce();
  });

  it.each([
    ['no TTS declaration', false, false, null],
    ['catalog is loading', true, true, null],
    ['catalog unavailable', true, false, 'extension catalog unavailable'],
  ] as const)('does not invent a Voice Studio action when %s', (_label, needsVoice, loading, error) => {
    state.catalogLoading = loading;
    state.catalogError = error;
    state.getPlugin.mockReturnValue({
      id: 'pocket-tts',
      supportsVoiceOutput: needsVoice,
    });
    render(<PluginStorePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Open plugin details' }));

    expect(screen.queryByRole('button', { name: /Open Voice Studio/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Open Pocket TTS/ })).toBeNull();
    expect(state.push).not.toHaveBeenCalled();
  });

  it('never exposes the shortcut for an uninstalled package', () => {
    if (!state.selectedPlugin) throw new Error('missing test fixture');
    state.selectedPlugin = { ...state.selectedPlugin, installed: false };
    render(<PluginStorePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Open plugin details' }));
    expect(screen.queryByRole('button', { name: /Open Voice Studio/ })).toBeNull();
    expect(state.push).not.toHaveBeenCalled();
  });

  it('does not use a different extension record as permission to configure voice', () => {
    state.getPlugin.mockImplementation((id: string) =>
      id === 'pocket-tts' ? undefined : { supportsVoiceOutput: true });
    render(<PluginStorePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Open plugin details' }));
    expect(screen.queryByRole('button', { name: /Open Voice Studio/ })).toBeNull();
    expect(state.push).not.toHaveBeenCalled();
  });
});
