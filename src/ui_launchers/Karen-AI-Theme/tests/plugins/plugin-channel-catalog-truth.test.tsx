import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import PluginOverviewPage from '@/components/plugins/PluginOverviewPage';

const { registry, health, registeredIds } = vi.hoisted(() => ({
  registry: vi.fn(),
  health: vi.fn(),
  registeredIds: vi.fn(),
}));

vi.mock('@/plugin_host/registry', () => ({
  usePluginRegistry: registry,
  usePluginHealth: health,
}));

vi.mock('@/plugin_host/loader', () => ({
  normalizePluginId: (id: string) => id,
  getRegisteredPluginIds: registeredIds,
  refreshImportMap: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiClient: { post: vi.fn() },
}));

const channel = {
  id: 'whatsapp-cloud',
  displayName: 'WhatsApp Cloud API Channel',
  description: 'Managed Meta transport; runtime-owned delivery',
  version: '1.0.0',
  rawStatus: 'disabled',
  enabled: false,
  has_gui: false,
  isCommunicationChannel: true,
  allowedRoles: ['admin'],
  promptFirstValid: true,
  menuContributions: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  registeredIds.mockReturnValue([]);
  registry.mockReturnValue({
    plugins: [channel],
    loading: false,
    error: null,
    refresh: vi.fn(),
  });
  health.mockReturnValue({
    backendState: 'disabled',
    frontendMountState: 'idle',
    errorMessage: undefined,
    permissionVisible: true,
  });
});

afterEach(cleanup);

describe('manifest-governed plugin UI health', () => {
  it('does not misdiagnose a backend-only WhatsApp adapter as unregistered UI', () => {
    render(<PluginOverviewPage />);
    expect(screen.getByText('WhatsApp Cloud API Channel')).toBeTruthy();
    expect(screen.getByText('not required (backend-only)')).toBeTruthy();
    expect(screen.getByText(/communication transport governed by ChannelHost/)).toBeTruthy();
    expect(screen.queryByText('UI installed but not registered. Retry registration to fix.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry Registration' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Enable' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Disable' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove UI only' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Install UI' })).toBeNull();
  });

  it('preserves the real missing-registration diagnostic for plugins declaring UI', () => {
    registry.mockReturnValue({
      plugins: [{ ...channel, id: 'ui-plugin', displayName: 'UI Plugin', has_gui: true, isCommunicationChannel: false }],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<PluginOverviewPage />);
    expect(screen.getByText('UI Plugin')).toBeTruthy();
    expect(screen.getByText('UI installed but not registered. Retry registration to fix.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry Registration' })).toBeTruthy();
    expect(screen.queryByText('not required (backend-only)')).toBeNull();
  });
});
