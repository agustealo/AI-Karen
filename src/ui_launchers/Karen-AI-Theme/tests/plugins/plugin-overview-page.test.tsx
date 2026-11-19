import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import PluginOverviewPage from '@/components/plugins/PluginOverviewPage';

const mockPost = vi.fn();
vi.mock('@/lib/api', () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
    get: vi.fn(),
  },
  apiClient: {
    post: (...args: unknown[]) => mockPost(...args),
    get: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

vi.mock('@/lib/useAuth', () => ({
  useAuth: () => ({ user: { id: 'admin-user', roles: ['admin'] } }),
}));

const mockPlugins = [
  {
    id: 'pocket-tts',
    displayName: 'Pocket TTS',
    description: 'Governed offline-first Kyutai Pocket TTS v4.0.1 CPU synthesis.',
    version: '1.0.0',
    enabled: true,
    has_gui: false,
    supportsVoiceOutput: true,
    promptFirstValid: true,
    menuContributions: [],
    rawStatus: 'enabled',
    allowedRoles: ['admin', 'user'],
  },
];

let currentPlugins = [...mockPlugins];
const mockRefresh = vi.fn().mockResolvedValue(undefined);

vi.mock('@/plugin_host/registry', () => ({
  usePluginRegistry: () => ({
    plugins: currentPlugins,
    loading: false,
    error: null,
    refresh: mockRefresh,
    getPlugin: (id: string) => currentPlugins.find((p) => p.id === id),
  }),
  usePluginHealth: (id: string) => {
    const plugin = currentPlugins.find((p) => p.id === id);
    return {
      pluginId: id,
      backendState: plugin?.rawStatus || 'uninstalled',
      frontendMountState: 'idle' as const,
      permissionVisible: true,
    };
  },
}));

vi.mock('@/plugin_host/loader', () => ({
  getRegisteredPluginIds: () => [],
  normalizePluginId: (id: string) => id.toLowerCase(),
  refreshImportMap: vi.fn().mockResolvedValue(undefined),
}));

describe('PluginOverviewPage Lifecycle and Affordance Contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockReset();
    currentPlugins = [
      {
        id: 'pocket-tts',
        displayName: 'Pocket TTS',
        description: 'Governed offline-first Kyutai Pocket TTS v4.0.1 CPU synthesis.',
        version: '1.0.0',
        enabled: true,
        has_gui: false,
        supportsVoiceOutput: true,
        promptFirstValid: true,
        menuContributions: [],
        rawStatus: 'enabled',
        allowedRoles: ['admin', 'user'],
      },
    ];
  });

  afterEach(cleanup);

  it('renders an enabled backend plugin with enabled badge and no lifecycle buttons for voice plugins', () => {
    render(<PluginOverviewPage />);

    expect(screen.getByText('Pocket TTS')).toBeTruthy();
    // The badge should render 'enabled' cleanly without '(discovered)' warning
    expect(screen.getByText('enabled')).toBeTruthy();
    expect(screen.queryByText('enabled (discovered)')).toBeNull();

    // Headless plugin should not be marked as regular missing UI
    expect(screen.getByText('Host-owned user workspace (no separate plugin bundle)')).toBeTruthy();

    // Voice plugins are opted in at install time; this page must not render
    // lifecycle buttons and must never call the refused legacy ingress.
    expect(screen.queryByRole('button', { name: 'Enable' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Disable' })).toBeNull();
    expect(
      screen.getByText('Enabled by install opt-in; no enable action is required here.'),
    ).toBeTruthy();

    // UI-only management buttons must not appear for headless plugins
    expect(screen.queryByRole('button', { name: 'Install UI' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove UI only' })).toBeNull();
  });

  it('opens the existing host-owned Voice Studio for backend-only synthesis plugins', () => {
    const openVoiceStudio = vi.fn();
    render(<PluginOverviewPage onOpenVoiceStudio={openVoiceStudio} />);
    expect(screen.getByText('Host-owned user workspace (no separate plugin bundle)')).toBeTruthy();
    expect(screen.getByText(/Pocket TTS has its own user workspace/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Install UI' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Open Voice Studio for Pocket TTS' }));
    expect(openVoiceStudio).toHaveBeenCalledOnce();
  });

  it('opens Pocket TTS from the plugin category without adding a fake frontend install', () => {
    const openPocketTts = vi.fn();
    render(<PluginOverviewPage onOpenPocketTts={openPocketTts} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open Pocket TTS workspace' }));
    expect(openPocketTts).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Install UI' })).toBeNull();
  });

  it('does not invent a Voice Studio action when the backend declares no synthesis modality', () => {
    currentPlugins = [{ ...mockPlugins[0], supportsVoiceOutput: false }];
    render(<PluginOverviewPage onOpenVoiceStudio={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Open Voice Studio/ })).toBeNull();
  });

  it('runs the governed disable flow: approval request, human confirm, verified execute', async () => {
    currentPlugins = [
      { ...mockPlugins[0], supportsVoiceOutput: false, id: 'sample-tool' },
    ];
    mockPost
      .mockResolvedValueOnce({
        status: 'pending',
        approval_id: '11111111-1111-4111-8111-111111111111',
        plugin_id: 'sample-tool',
        action: 'disable',
        expires_at: '2026-01-01T00:00:00Z',
      })
      .mockResolvedValueOnce({ status: 'approved' })
      .mockResolvedValueOnce({ status: 'verified_committed' });

    render(<PluginOverviewPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Disable' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/plugins/sample-tool/lifecycle/disable/approval',
      );
    });

    // The final click is an explicit confirmation of the pending receipt.
    fireEvent.click(screen.getByRole('button', { name: 'Confirm disable' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/approvals/11111111-1111-4111-8111-111111111111/decision',
        { decision: 'approved' },
      );
      expect(mockPost).toHaveBeenCalledWith(
        '/api/plugins/sample-tool/lifecycle/disable/execute',
        { approval_id: '11111111-1111-4111-8111-111111111111' },
      );
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Enable' })).toBeTruthy();
    });
    expect(mockPost).not.toHaveBeenCalledWith('/api/extensions/sample-tool/unload');
  });

  it('runs the governed enable flow and never calls the refused legacy load route', async () => {
    currentPlugins = [
      {
        ...mockPlugins[0],
        supportsVoiceOutput: false,
        id: 'sample-tool',
        enabled: false,
        rawStatus: 'disabled',
      },
    ];
    mockPost
      .mockResolvedValueOnce({
        status: 'pending',
        approval_id: '22222222-2222-4222-8222-222222222222',
        plugin_id: 'sample-tool',
        action: 'enable',
        expires_at: '2026-01-01T00:00:00Z',
      })
      .mockResolvedValueOnce({ status: 'approved' })
      .mockResolvedValueOnce({ status: 'verified_committed' });

    render(<PluginOverviewPage />);

    expect(screen.getByText('disabled')).toBeTruthy();

    const enableButton = screen.getByRole('button', { name: 'Enable' });
    expect(enableButton).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Disable' })).toBeNull();

    fireEvent.click(enableButton);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/plugins/sample-tool/lifecycle/enable/approval',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Confirm enable' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/approvals/22222222-2222-4222-8222-222222222222/decision',
        { decision: 'approved' },
      );
      expect(mockPost).toHaveBeenCalledWith(
        '/api/plugins/sample-tool/lifecycle/enable/execute',
        { approval_id: '22222222-2222-4222-8222-222222222222' },
      );
    });

    // Proves the button transitions to Disable and is not stuck on Enable
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Disable' })).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Enable' })).toBeNull();
      expect(screen.getByText('enabled')).toBeTruthy();
      expect(screen.queryByText('enabled (discovered)')).toBeNull();
    });

    expect(mockPost).not.toHaveBeenCalledWith('/api/extensions/pocket-tts/load');
    expect(mockPost).not.toHaveBeenCalledWith('/api/extensions/sample-tool/load');
  });
});
