// @vitest-environment jsdom
import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocked = vi.hoisted(() => ({
  usePluginRegistry: vi.fn(),
  usePluginHealth: vi.fn(),
  getRegisteredPluginIds: vi.fn(),
}));

vi.mock('@/plugin_host/registry', () => ({
  usePluginRegistry: mocked.usePluginRegistry,
  usePluginHealth: mocked.usePluginHealth,
}));

vi.mock('@/plugin_host/loader', () => ({
  getRegisteredPluginIds: mocked.getRegisteredPluginIds,
  normalizePluginId: (id: string) => id,
  refreshImportMap: vi.fn(),
}));

vi.mock('./PluginRecommendedModels', () => ({
  PluginRecommendedModels: () => null,
}));

vi.mock('@/lib/api', () => ({
  apiClient: { post: vi.fn() },
}));

import PluginOverviewPage from './PluginOverviewPage';

const installed = [
  {
    id: 'extension-alpha',
    displayName: 'Alpha',
    description: 'Backend extension with UI',
    version: '1.2.0',
    has_gui: true,
    isCommunicationChannel: false,
    supportsVoiceOutput: false,
    rawStatus: 'active',
  },
  {
    id: 'channel-beta',
    displayName: 'Beta',
    description: 'Governed communication transport',
    version: '2.0.0',
    has_gui: false,
    isCommunicationChannel: true,
    supportsVoiceOutput: false,
    rawStatus: 'disabled',
  },
];

beforeEach(() => {
  mocked.usePluginRegistry.mockReset();
  mocked.usePluginHealth.mockReset();
  mocked.getRegisteredPluginIds.mockReset();
  mocked.getRegisteredPluginIds.mockReturnValue(['extension-alpha']);
  mocked.usePluginHealth.mockImplementation((id: string) => ({
    backendState: id === 'extension-alpha' || id === 'voice-output' ? 'active' : 'disabled',
    frontendMountState: id === 'extension-alpha' ? 'mounted' : 'idle',
    permissionVisible: true,
    errorMessage: '',
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Plugins and Tools Kari OS workspace', () => {
  it('uses the approved shared root without inventing plugin execution state', () => {
    mocked.usePluginRegistry.mockReturnValue({
      plugins: installed,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    const { container } = render(<PluginOverviewPage />);
    expect(container.querySelector('[data-testid="plugins-overview"][data-kari-root]')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Plugins & Tools' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /Upload and install a plugin/ }).getAttribute('href')).toBe('/plugins');
    expect(screen.getByTestId('plugin-count').textContent?.trim()).toBe('2');
    expect(screen.getByTestId('plugin-ui-count').textContent?.trim()).toBe('1');
    expect(screen.getByTestId('plugin-channel-count').textContent?.trim()).toBe('1');
    expect(screen.getAllByTestId('plugin-integration-card')).toHaveLength(2);
    expect(screen.getByText('Governed communication transport')).toBeTruthy();
    expect(container.querySelectorAll('.kari-card').length).toBeGreaterThanOrEqual(5);
  });

  it('does not misreport a broken backend as a failed UI installation', () => {
    mocked.usePluginRegistry.mockReturnValue({
      plugins: [{ ...installed[0], rawStatus: 'broken' }],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    mocked.usePluginHealth.mockReturnValue({
      backendState: 'broken',
      frontendMountState: 'idle',
      permissionVisible: true,
      errorMessage: 'Plugin lifecycle outcome is unverified',
    });
    render(<PluginOverviewPage />);
    const card = screen.getByTestId('plugin-integration-card');
    expect(card.textContent).toContain('unverified');
    expect(card.textContent).toContain('broken');
    expect(card.textContent).not.toContain('UI installation error');
  });

  it('renders voice plugin lifecycle guidance without a missing icon crash', () => {
    mocked.usePluginRegistry.mockReturnValue({
      plugins: [
        {
          ...installed[0],
          id: 'voice-output',
          displayName: 'Voice output',
          supportsVoiceOutput: true,
          rawStatus: 'active',
        },
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<PluginOverviewPage />);
    expect(screen.getByText(
      'Enabled by install opt-in; no enable action is required here.',
    )).toBeTruthy();
  });

  it('discloses loading and backend errors without fabricated counts', () => {
    mocked.usePluginRegistry.mockReturnValue({
      plugins: [],
      loading: true,
      error: null,
      refresh: vi.fn(),
    });
    const view = render(<PluginOverviewPage />);
    expect(screen.getByRole('status').textContent).toContain('Loading the live plugin registry');
    expect(screen.getByTestId('plugin-count').textContent?.trim()).toBe('—');
    expect(screen.getByTestId('plugin-ui-count').textContent?.trim()).toBe('—');

    mocked.usePluginRegistry.mockReturnValue({
      plugins: [],
      loading: false,
      error: 'Registry unavailable',
      refresh: vi.fn(),
    });
    view.rerender(<PluginOverviewPage />);
    expect(screen.getByText('Registry unavailable')).toBeTruthy();
    expect(screen.getByTestId('plugin-count').textContent?.trim()).toBe('—');
  });

  it('distinguishes an empty verified registry from load failure', () => {
    mocked.usePluginRegistry.mockReturnValue({
      plugins: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<PluginOverviewPage />);
    expect(screen.getByText('No plugins discovered')).toBeTruthy();
    expect(screen.getByTestId('plugin-count').textContent?.trim()).toBe('0');
  });
});
