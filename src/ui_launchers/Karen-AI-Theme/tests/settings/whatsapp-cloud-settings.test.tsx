import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import WhatsAppCloudSettings from '@/components/settings/WhatsAppCloudSettings';
import { apiClient, ApiError } from '@/lib/api';

const { auth } = vi.hoisted(() => ({
  auth: {
    isAuthenticated: true,
    isLoading: false,
    user: {
      tenant_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      user_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    },
  },
}));

vi.mock('@/lib/useAuth', () => ({ useAuth: () => auth }));
vi.mock('@/lib/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const endpoint = '/api/channels/operator/whatsapp/connections';
const id = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
const stored = { connection_id: id, connection_revision: 1, enabled: false };
const activated = { ...stored, connection_revision: 2, enabled: true };

function operation(
  stage: 'provisioned' | 'activated' | 'deactivated',
  connection = stage === 'activated' ? activated : stored,
) {
  return {
    ...connection,
    stage,
    provider_phone_verified: stage === 'activated',
    webhook_subscription_verified: false,
    signed_inbound_verified: false,
    delivery_verified: false,
  };
}

beforeEach(() => {
  auth.isAuthenticated = true;
  auth.isLoading = false;
  auth.user.tenant_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  auth.user.user_id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
  vi.mocked(apiClient.get).mockResolvedValue({ connections: [] });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe('governed WhatsApp Cloud operator settings', () => {
  it('reads only persisted backend state and does not claim live Meta health', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ connections: [stored] });
    render(<WhatsAppCloudSettings />);
    expect(await screen.findByText(id)).toBeTruthy();
    expect(screen.getByText('Disabled in Karen')).toBeTruthy();
    expect(screen.getByText(/Signed webhook and delivery unverified/)).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith(endpoint);
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.queryByText(/WhatsApp connected successfully/)).toBeNull();
  });

  it('provisions only a disabled account using an opaque Vault handle', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(operation('provisioned'));
    render(<WhatsAppCloudSettings />);
    expect(await screen.findByText(/No WhatsApp Cloud connections found/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Meta phone-number ID'), {
      target: { value: '30987654321' },
    });
    fireEvent.change(screen.getByLabelText('Existing Vault credential handle'), {
      target: { value: 'vault://scoped-wa' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Provision disabled account' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(endpoint, {
      provider_account_id: '30987654321',
      credential_handle: 'vault://scoped-wa',
    }));
    expect(await screen.findByText(/Account provisioned as disabled/)).toBeTruthy();
    expect((screen.getByLabelText('Existing Vault credential handle') as HTMLInputElement).value)
      .toBe('');
    expect(screen.queryByText('vault://scoped-wa')).toBeNull();
  });

  it('activates only the current persisted revision and describes unverified delivery', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ connections: [stored] })
      .mockResolvedValueOnce({ connections: [activated] });
    vi.mocked(apiClient.post).mockResolvedValue(operation('activated'));
    render(<WhatsAppCloudSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Activate connection' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(
      `${endpoint}/${id}/activate`,
      { expected_revision: 1 },
    ));
    expect(await screen.findByText(/Meta phone identity checked/)).toBeTruthy();
    expect(await screen.findByText('Enabled in Karen (live status unverified)')).toBeTruthy();
    expect(screen.getByText(/Signed webhook and delivery unverified/)).toBeTruthy();
  });

  it('deactivates with backend revision and never claims external Meta unsubscribe', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ connections: [activated] })
      .mockResolvedValueOnce({ connections: [stored] });
    vi.mocked(apiClient.post).mockResolvedValue(
      operation('deactivated', { ...stored, connection_revision: 3 }),
    );
    render(<WhatsAppCloudSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate connection' }));
    expect(await screen.findByText(/External Meta subscription removal is not verified/))
      .toBeTruthy();
    expect(apiClient.post).toHaveBeenCalledWith(
      `${endpoint}/${id}/deactivate`,
      { expected_revision: 2 },
    );
  });

  it('fails closed on forged provider success without storing fake active state', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ connections: [stored] });
    vi.mocked(apiClient.post).mockResolvedValue({
      ...operation('activated'),
      delivery_verified: true,
    });
    render(<WhatsAppCloudSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Activate connection' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'could not verify the WhatsApp operation',
    );
    expect(screen.queryByText('Enabled in Karen (live status unverified)')).toBeNull();
    expect(screen.queryByText(/Meta phone identity checked/)).toBeNull();
  });

  it('rejects malformed inventory and never shows an empty account state', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      connections: [{ ...stored, credential_handle: 'vault://private' }],
    });
    render(<WhatsAppCloudSettings />);
    expect((await screen.findByRole('alert')).textContent).toContain(
      'could not verify the WhatsApp operation',
    );
    expect(screen.queryByText(/No WhatsApp Cloud connections found/)).toBeNull();
    expect(screen.queryByText('vault://private')).toBeNull();
  });

  it('returns stale revision errors without replaying a mutation', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ connections: [stored] });
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, 'stale vault://private'));
    render(<WhatsAppCloudSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Activate connection' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Connection changed. Refresh the inventory',
    );
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('vault://private')).toBeNull();
    expect(screen.queryByText('Enabled in Karen (live status unverified)')).toBeNull();
  });

  it('does not inspect or mutate backend state while signed out', async () => {
    auth.isAuthenticated = false;
    render(<WhatsAppCloudSettings />);
    expect((await screen.findByRole('alert')).textContent).toContain('Sign in');
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect((screen.getByRole('button', { name: 'Provision disabled account' }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it('clears old tenant state and reads backend inventory after principal change', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ connections: [stored] })
      .mockResolvedValueOnce({ connections: [] });
    const view = render(<WhatsAppCloudSettings />);
    expect(await screen.findByText(id)).toBeTruthy();
    auth.user.tenant_id = 'dddddddd-dddd-dddd-dddd-dddddddddddd';
    view.rerender(<WhatsAppCloudSettings />);
    expect(await screen.findByText(/No WhatsApp Cloud connections found/)).toBeTruthy();
    expect(screen.queryByText(id)).toBeNull();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });
});
