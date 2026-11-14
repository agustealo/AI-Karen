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
  active_consent_provider_ids: [] as string[],
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
  has_active_consent: false,
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
          has_active_consent: vi.mocked(apiClient.post).mock.calls.length > 0,
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
          has_active_consent: vi.mocked(apiClient.post).mock.calls.length === 0,
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


describe('KOC-05 disabled-provider and obsolete-policy consent revocation', () => {
  it('retains revocation-only controls after the managed provider is disabled', async () => {
    const disabled = {
      ...channel,
      active_consent_provider_ids: ['managed-operator'],
    };
    let revoked = false;
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        return { connections: [disabled] };
      }
      if (path === consentPath) {
        return {
          ...currentConsent,
          acknowledged: false,
          has_active_consent: !revoked,
        };
      }
      throw new Error('Unexpected request');
    });
    vi.mocked(apiClient.post).mockImplementation(async (path) => {
      expect(path).toBe(revokePath);
      revoked = true;
      return { revoked: true, paired: false, provider_unlinked: false };
    });

    render(<ChannelsSettings />);
    expect(await screen.findByText('Previous-policy acknowledgement still active')).toBeTruthy();
    expect(screen.getByText(/no longer configured/)).toBeTruthy();
    expect(screen.getByText('Unavailable')).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
    fireEvent.click(screen.getByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    }));
    expect(await screen.findByText(/Risk acknowledgement revoked in Karen/)).toBeTruthy();
    expect(screen.getByText('Not acknowledged')).toBeTruthy();
    expect(screen.getByText('Not verified connected')).toBeTruthy();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenCalledWith(revokePath, {});
    expect(vi.mocked(apiClient.get).mock.calls.filter(([p]) => p === consentPath)).toHaveLength(2);
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it('shows a revocation action for an obsolete policy even when the provider is configured', async () => {
    mockInventoryAndConsent({ connections: [configuredChannel] }, {
      ...currentConsent,
      acknowledged: false,
      has_active_consent: true,
    });
    render(<ChannelsSettings />);
    expect(await screen.findByText('Previous-policy acknowledgement still active')).toBeTruthy();
    expect(screen.getByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('fails closed when a disabled-provider consent status cannot be verified', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        return { connections: [{
          ...channel, active_consent_provider_ids: ['managed-operator'],
        }] };
      }
      throw new Error('Consent backend unavailable');
    });
    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent)
      .toContain('Current consent could not be verified');
    expect(screen.queryByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it('rejects a missing or malformed active-consent inventory instead of inventing no consents', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      connections: [{ ...channel, active_consent_provider_ids: ['managed-operator', 'managed-operator'] }],
    });
    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent)
      .toContain('could not verify your channel connections');
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it('refuses to accept risks for an inactive provider when no consent exists', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      connections: [{ ...channel, active_consent_provider_ids: [] }],
    });
    render(<ChannelsSettings />);
    await screen.findByText('whatsapp-cloud');
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Acknowledge risks' })).toBeNull();
    expect(screen.queryByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});


describe('KOC-05 host-independent stored consent recovery', () => {
  const recoveryEndpoint = '/api/channels/personal/consent-recovery';
  const retired = {
    connection_id: configuredChannel.connection_id,
    provider_id: 'retired-provider',
    policy_version: 'old-unofficial-risk-policy',
  };
  const revokeEndpoint = recoveryEndpoint + '/' + retired.connection_id +
    '/' + retired.provider_id + '/revoke';

  it('loads owner-scoped durable consent when ChannelHost inventory is unavailable', async () => {
    let withdrawn = false;
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        throw new ApiError(503, 'Host stopped');
      }
      if (path === recoveryEndpoint) {
        return { consents: withdrawn ? [] : [retired] };
      }
      throw new Error('Unexpected recovery URL');
    });
    vi.mocked(apiClient.post).mockImplementation(async (path) => {
      expect(path).toBe(revokeEndpoint);
      withdrawn = true;
      return { revoked: true, paired: false, provider_unlinked: false };
    });

    render(<ChannelsSettings />);
    expect((await screen.findByRole('alert')).textContent)
      .toContain('Channels service is unavailable');

    expect(apiClient.get).not.toHaveBeenCalledWith(recoveryEndpoint);
    fireEvent.click(screen.getByRole('button', { name: 'Review stored channel consent' }));
    expect(await screen.findByText('retired-provider')).toBeTruthy();
    expect(screen.getByText(/Recorded policy: old-unofficial-risk-policy/)).toBeTruthy();
    expect(screen.getByText(/not proof of provider-side data deletion/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    }));
    expect(await screen.findByText(/Stored consent revocation verified/)).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    })).toBeNull();
    expect(apiClient.post).toHaveBeenCalledOnce();
    expect(apiClient.post).toHaveBeenCalledWith(revokeEndpoint, {});
    expect(vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === recoveryEndpoint))
      .toHaveLength(2);
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it('does not automatically replay a recovery mutation after ambiguous outcome', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') return { connections: [] };
      if (path === recoveryEndpoint) return { consents: [retired] };
      throw new Error('Unexpected URL');
    });
    vi.mocked(apiClient.post).mockRejectedValue(new Error('provider-secret-in-error'));
    render(<ChannelsSettings />);
    fireEvent.click(await screen.findByRole('button', {
      name: 'Review stored channel consent',
    }));
    fireEvent.click(await screen.findByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Revocation outcome unverified');
    expect(alert.textContent).not.toContain('provider-secret');
    expect(screen.queryByText(/Stored consent revocation verified/)).toBeNull();
    expect(apiClient.post).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    })).toBeNull();
  });

  it('rejects mutation success when the old consent remains in the durable re-read', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') return { connections: [] };
      if (path === recoveryEndpoint) return { consents: [retired] };
      throw new Error('Unexpected URL');
    });
    vi.mocked(apiClient.post).mockResolvedValue({
      revoked: true, paired: false, provider_unlinked: false,
    });
    render(<ChannelsSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'Review stored channel consent' }));
    fireEvent.click(await screen.findByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    }));
    expect((await screen.findByRole('alert')).textContent)
      .toContain('Revocation outcome unverified');
    expect(apiClient.post).toHaveBeenCalledOnce();
  });

  it('fails closed on malformed or duplicate recovery inventory', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') return { connections: [] };
      if (path === recoveryEndpoint) return { consents: [retired, retired] };
      throw new Error('Unexpected URL');
    });
    render(<ChannelsSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'Review stored channel consent' }));
    expect((await screen.findByRole('alert')).textContent)
      .toContain('Stored channel consent could not be verified');
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    })).toBeNull();
  });

  it('hides recovery mutation when the normal channel card already covers that consent', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/channels/personal/connections') {
        return { connections: [{
          ...channel,
          active_consent_provider_ids: [retired.provider_id],
        }] };
      }
      if (path === '/api/channels/personal/' + channel.connection_id + '/' +
          retired.provider_id + '/consent') {
        return {
          ...currentConsent, has_active_consent: true,
        };
      }
      if (path === recoveryEndpoint) return { consents: [retired] };
      throw new Error('Unexpected URL');
    });
    render(<ChannelsSettings />);
    await screen.findByRole('button', {
      name: 'Revoke personal WhatsApp risk consent',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review stored channel consent' }));
    expect(await screen.findByText(/No separate active stored consent/)).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Revoke stored consent for retired-provider',
    })).toBeNull();
  });

  it('does not fetch private recovery state before authentication', async () => {
    auth.isAuthenticated = false;
    render(<ChannelsSettings />);
    const review = screen.getByRole('button', {
      name: 'Review stored channel consent',
    }) as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
