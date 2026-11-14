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
  provider_id: null,
  availability: 'unavailable' as const,
  last_observed_phase: 'connected',
  live_connected: false,
  qr_available: false,
  provider_unlinked: false,
};


const configuredChannel = {
  ...channel,
  provider_id: 'managed-operator',
  availability: 'configured' as const,
};

const consentPath = '/api/channels/personal/' +
  configuredChannel.connection_id + '/' + configuredChannel.provider_id + '/consent';
const revokePath = consentPath.replace(/\/consent$/, '/revoke');

const currentConsent = {
  acknowledged: false,
  policy_version: 'whatsapp-personal-risk-v2',
  notice_title: 'Connect personal WhatsApp (unofficial integration)',
  notice_text: 'This connection is unofficial and may expose private metadata and cause account suspension.',
  paired: false,
  provider_unlinked: false,
};

function mockInventoryAndConsent(
  inventory: unknown = { connections: [configuredChannel] },
  consent: unknown = currentConsent,
) {
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === '/api/channels/personal/connections') {
      return inventory;
    }
    if (path === consentPath) {
      return consent;
    }
    throw new Error('Unexpected backend request');
  });
}

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


describe('KOC-05 versioned risk acknowledgement and revocation', () => {
  it('displays backend-owned risk notice and uses its policy version only after explicit checkbox', async () => {
    mockInventoryAndConsent();
    vi.mocked(apiClient.post).mockResolvedValue({
      acknowledged: true, paired: false, provider_unlinked: false,
    });
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        return { connections: [configuredChannel] };
      }
      if (path === consentPath) {
        return {
          ...currentConsent,
          acknowledged: vi.mocked(apiClient.post).mock.calls.length > 0,
        };
      }
      throw new Error('Unexpected backend request');
    });

    render(<ChannelsSettings />);
    expect(await screen.findByText(currentConsent.notice_title)).toBeTruthy();
    expect(screen.getByText(currentConsent.notice_text)).toBeTruthy();
    const acknowledge = screen.getByRole('button', { name: 'Acknowledge risks' });
    expect((acknowledge as HTMLButtonElement).disabled).toBe(true);
    expect(apiClient.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('checkbox', {
      name: 'I explicitly accept the personal WhatsApp risks',
    }));
    expect((acknowledge as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(acknowledge);

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(
      consentPath,
      { accepted: true, policy_version: 'whatsapp-personal-risk-v2' },
    ));
    expect(await screen.findByText(/Risk acknowledgement verified in Karen/)).toBeTruthy();
    expect(screen.getByText('Acknowledged')).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith(consentPath);
    expect(vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === consentPath).length).toBe(2);
    expect(screen.getByText('Not verified connected')).toBeTruthy();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it('revokes already persisted consent and never claims external unlink or credential deletion', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      revoked: true, paired: false, provider_unlinked: false,
    });
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        return { connections: [configuredChannel] };
      }
      if (path === consentPath) {
        return {
          ...currentConsent,
          acknowledged: vi.mocked(apiClient.post).mock.calls.length === 0,
        };
      }
      throw new Error('Unexpected backend request');
    });
    render(<ChannelsSettings />);
    fireEvent.click(await screen.findByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(revokePath, {}));
    expect(await screen.findByText(/Remote unlink and credential erasure are not verified/)).toBeTruthy();
    expect(screen.getByText('Not acknowledged')).toBeTruthy();
    expect(screen.getByText('Not verified connected')).toBeTruthy();
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it('fails closed after ambiguous mutation receipt and never retries the POST', async () => {
    mockInventoryAndConsent();
    vi.mocked(apiClient.post).mockRejectedValue(new Error('receipt lost'));
    render(<ChannelsSettings />);
    await screen.findByText(currentConsent.notice_title);
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'I explicitly accept the personal WhatsApp risks',
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge risks' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Refresh status before trying again');
    expect(screen.queryByText('Acknowledged')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', {
      name: 'Refresh personal channel consent',
    }));
    await screen.findByText(currentConsent.notice_title);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it('rejects a success receipt if the durable re-read remains unacknowledged', async () => {
    mockInventoryAndConsent();
    vi.mocked(apiClient.post).mockResolvedValue({
      acknowledged: true, paired: false, provider_unlinked: false,
    });
    render(<ChannelsSettings />);
    await screen.findByText(currentConsent.notice_title);
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'I explicitly accept the personal WhatsApp risks',
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge risks' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Consent change unverified');
    expect(screen.queryByText('Acknowledged')).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it('does not enable consent when provider is not configured', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      connections: [{ ...configuredChannel, provider_id: null, availability: 'unavailable' }],
    });
    render(<ChannelsSettings />);
    await screen.findByText('whatsapp-cloud');
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it('does not present agreement controls if the backend risk notice cannot be verified', async () => {
    mockInventoryAndConsent(
      { connections: [configuredChannel] },
      { acknowledged: false, policy_version: 'v1', paired: false, provider_unlinked: false },
    );
    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent).toContain('Current consent could not be verified');
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
  });
});
