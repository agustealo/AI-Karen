import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import ChannelsSettings from '@/components/settings/ChannelsSettings';
import { apiClient, ApiError } from '@/lib/api';

const { auth } = vi.hoisted(() => ({
  auth: { isAuthenticated: true, isLoading: false },
}));

vi.mock('@/lib/useAuth', () => ({
  useAuth: () => auth,
}));

vi.mock('@/lib/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const channel = {
  connection_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
  installation_id: 'whatsapp-cloud',
  provider_id: 'managed-operator',
  availability: 'configured' as const,
  last_observed_phase: 'connected',
  live_connected: false,
  qr_available: false,
  provider_unlinked: false,
};

beforeEach(() => {
  auth.isAuthenticated = true;
  auth.isLoading = false;
  vi.mocked(apiClient.get).mockResolvedValue({ connections: [] });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe('KOC-05 personal Channels truth-only settings', () => {
  it('displays only assigned backend channels and treats stored connected events as historical', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ connections: [channel] });
    render(<ChannelsSettings />);
    expect(await screen.findByText('whatsapp-cloud')).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith('/api/channels/personal/connections');
    expect(screen.getByText('Not verified connected')).toBeTruthy();
    expect(screen.getByText(/connected \(historical, not a health check\)/)).toBeTruthy();
    expect(screen.queryByText('Reported connected by Karen')).toBeNull();
    expect(screen.queryByText('vault://private')).toBeNull();
    expect(screen.queryByRole('button', { name: /connect whatsapp/i })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.put).not.toHaveBeenCalled();
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it('distinguishes an authenticated empty inventory from disabled transport', async () => {
    render(<ChannelsSettings />);
    expect(await screen.findByText('No assigned personal connections')).toBeTruthy();
    expect(screen.getByText(/does not indicate whether a provider/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('reports upstream outage without displaying empty or connected status', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(503, 'Backend unavailable'));
    render(<ChannelsSettings />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Channels service is unavailable');
    expect(screen.queryByText('No assigned personal connections')).toBeNull();
    expect(screen.queryByText('Reported connected by Karen')).toBeNull();
  });

  it('rejects malformed or missing inventory rather than claiming no connections', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ connections: [{ ...channel, live_connected: 'true' }] });
    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent).toContain('could not verify');
    expect(screen.queryByText('No assigned personal connections')).toBeNull();
  });

  it('does not query private channel state without authentication', async () => {
    auth.isAuthenticated = false;
    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent).toContain('Sign in');
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('refreshes backend truth without keeping a formerly connected state visible', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({
        connections: [{ ...channel, live_connected: true }],
      })
      .mockRejectedValueOnce(new ApiError(403, 'denied'));
    render(<ChannelsSettings />);
    expect(await screen.findByText('Reported connected by Karen')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh channel inventory' }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect((await screen.findByRole('alert')).textContent).toContain('did not authorize');
    expect(screen.queryByText('Reported connected by Karen')).toBeNull();
  });

  it('never interprets an unlink receipt as verified credential deletion', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      connections: [{ ...channel, provider_unlinked: true }],
    });
    render(<ChannelsSettings />);
    expect(await screen.findByText(/not proof of credential or message-data erasure/)).toBeTruthy();
  });
});
