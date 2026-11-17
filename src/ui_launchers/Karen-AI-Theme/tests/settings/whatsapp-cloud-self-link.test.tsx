import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import WhatsAppCloudSelfLink from '@/components/settings/WhatsAppCloudSelfLink';
import { apiClient, ApiError } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  apiClient: { post: vi.fn(), get: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const ID = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
const OTHER = 'dddddddd-dddd-dddd-dddd-dddddddddddd';
const TOKEN = 'a'.repeat(43);
const COMMAND = '/link ' + TOKEN;
const ENDPOINT = `/api/channels/identity/whatsapp/connections/${ID}/challenge`;
const challenge = {
  challenge_id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
  command: COMMAND,
  expires_in_seconds: 600,
};
const STATUS_ENDPOINT = `/api/channels/identity/whatsapp/connections/${ID}/challenges/${challenge.challenge_id}/status`;

function enterConnection(value = ID) {
  fireEvent.change(screen.getByLabelText('Operator-provided connection ID'), {
    target: { value },
  });
}

beforeEach(() => {
  vi.mocked(apiClient.post).mockResolvedValue(challenge);
  vi.mocked(apiClient.get).mockResolvedValue({
    challenge_id: challenge.challenge_id,
    status: 'pending',
    evidence_basis: 'host_link_challenge_ledger',
    current_binding_verified: false,
    delivery_verified: false,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

describe('WhatsApp Cloud single-use consumer self-link', () => {
  it('does nothing until an operator-provided UUID and explicit click', async () => {
    render(<WhatsAppCloudSelfLink />);
    const request = screen.getByRole('button', { name: 'Request one-time link command' });
    expect((request as HTMLButtonElement).disabled).toBe(true);
    enterConnection('not-a-uuid');
    expect((request as HTMLButtonElement).disabled).toBe(true);
    expect(apiClient.post).not.toHaveBeenCalled();

    enterConnection();
    fireEvent.click(request);
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(ENDPOINT, {}));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(await screen.findByLabelText('One-time WhatsApp link command')).toBeTruthy();
    expect(screen.getByText(/Command issued does not mean the sender is linked/))
      .toBeTruthy();
    expect(screen.getByText(/Live ChatRuntime and delivery remain unverified/))
      .toBeTruthy();
  });

  it('retains the secret only transiently and clears it explicitly or on a new connection', async () => {
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect((await screen.findByLabelText('One-time WhatsApp link command')).textContent)
      .toBe(COMMAND);
    fireEvent.click(screen.getByRole('button', { name: 'Clear command from screen' }));
    expect(screen.queryByText(COMMAND)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    enterConnection(OTHER);
    expect(screen.queryByText(COMMAND)).toBeNull();
  });

  it('discards a response that finishes after the principal component is unmounted', async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(apiClient.post).mockImplementationOnce(
      () => new Promise((done) => { resolve = done; }),
    );
    const view = render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    view.unmount();
    resolve(challenge);
    await Promise.resolve();
    expect(screen.queryByText(COMMAND)).toBeNull();
  });

  it('expires the command from the screen at the host-declared TTL', async () => {
    const timer = vi.spyOn(window, 'setTimeout');
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    const expiry = timer.mock.calls.find((args) => args[1] === 600_000);
    expect(expiry).toBeDefined();
    await act(async () => {
      const callback = expiry?.[0];
      if (typeof callback === 'function') callback();
    });
    expect(screen.queryByText(COMMAND)).toBeNull();
    timer.mockRestore();
  });

  it.each([
    { ...challenge, command: '/link short' },
    { ...challenge, command: '/link ' + '!' + 'a'.repeat(42) },
    { ...challenge, expires_in_seconds: 3600 },
    { ...challenge, expires_in_seconds: true },
    { ...challenge, tenant_id: 'forged' },
    { ...challenge, challenge_id: 'not-a-uuid' },
    { ...challenge, command: 'fake meta connected' },
  ])('rejects unexpected or forged challenge responses without showing a token', async (invalid) => {
    vi.mocked(apiClient.post).mockResolvedValue(invalid);
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'could not verify the identity-link request',
    );
    expect(screen.queryByText(COMMAND)).toBeNull();
    expect(screen.queryByText(/sender is linked successfully/i)).toBeNull();
  });

  it('redacts a backend error containing an external secret', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(
      403, 'Secret provider token should not appear',
    ));
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'not authorized for identity linking',
    );
    expect(screen.queryByText(/Secret provider token/)).toBeNull();
    expect(screen.queryByText(COMMAND)).toBeNull();
  });

  it('does not automatically check backend link status when a command is issued', async () => {
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    expect(apiClient.get).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith(STATUS_ENDPOINT));
    expect(screen.getByText(/has not recorded a consumed proof/)).toBeTruthy();
    expect(screen.getByText(/does not independently verify Meta origin/)).toBeTruthy();
  });

  it('shows only durable signed-ingress consumption, then drops the bearer secret', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      challenge_id: challenge.challenge_id,
      status: 'consumed',
      evidence_basis: 'host_link_challenge_ledger',
      current_binding_verified: false,
      delivery_verified: false,
    });
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
    expect(await screen.findByText(/successful one-time proof consumption/)).toBeTruthy();
    expect(screen.queryByText(COMMAND)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Copy command' })).toBeNull();
    expect(screen.getByText(/not confirmation of a currently active sender binding/)).toBeTruthy();
  });

  it.each(['expired', 'revoked', 'invalidated'])(
    'removes the one-time command on %s without claiming provider success',
    async (status) => {
      vi.mocked(apiClient.get).mockResolvedValue({
        challenge_id: challenge.challenge_id,
        status,
        evidence_basis: 'host_link_challenge_ledger',
        current_binding_verified: false,
        delivery_verified: false,
      });
      render(<WhatsAppCloudSelfLink />);
      enterConnection();
      fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
      expect(await screen.findByText(COMMAND)).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
      await waitFor(() => expect(screen.queryByText(COMMAND)).toBeNull());
      expect(screen.queryByText(/sender linked successfully/i)).toBeNull();
      expect(screen.getByRole('status')).toBeTruthy();
    },
  );

  it.each([
    { challenge_id: OTHER, status: 'consumed' },
    { challenge_id: challenge.challenge_id, status: 'meta_certified' },
    { challenge_id: challenge.challenge_id, status: 'consumed', delivery_verified: true },
    { challenge_id: challenge.challenge_id, status: 'pending', current_binding_verified: true },
    { challenge_id: challenge.challenge_id, status: 'consumed', provider_message_id: 'secret' },
  ])('refuses forged status responses and retains no false provider claim', async (override) => {
    vi.mocked(apiClient.get).mockResolvedValue({
      evidence_basis: 'host_link_challenge_ledger',
      current_binding_verified: false,
      delivery_verified: false,
      ...override,
    });
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'could not verify the identity-link request',
    );
    expect(screen.queryByText(/successful one-time proof consumption/)).toBeNull();
    // Static guidance says 'treat it as a secret'; it is the attacker-supplied\n    // value itself that must never appear as rendered content.\n    expect(screen.queryByText('secret')).toBeNull();
  });

  it('preserves only a challenge reference after the command expires', async () => {
    const timer = vi.spyOn(window, 'setTimeout');
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    const expiration = timer.mock.calls.find((args) => args[1] === 600_000);
    expect(expiration).toBeDefined();
    await act(async () => {
      const callback = expiration?.[0];
      if (typeof callback === 'function') callback();
    });
    expect(screen.queryByText(COMMAND)).toBeNull();
    expect(screen.getByRole('button', { name: 'Check link proof status' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith(STATUS_ENDPOINT));
    timer.mockRestore();
  });

  it('discards a status response after connection change or unmount', async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(apiClient.get).mockImplementationOnce(
      () => new Promise((done) => { resolve = done; }),
    );
    const view = render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Check link proof status' }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    enterConnection(OTHER);
    resolve({
      challenge_id: challenge.challenge_id,
      status: 'consumed',
      evidence_basis: 'host_link_challenge_ledger',
      current_binding_verified: false,
      delivery_verified: false,
    });
    await Promise.resolve();
    expect(screen.queryByText(/successful one-time proof consumption/)).toBeNull();
    view.unmount();
  });

  it('does not automatically copy credentials to the clipboard', async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: copy },
    });
    render(<WhatsAppCloudSelfLink />);
    enterConnection();
    fireEvent.click(screen.getByRole('button', { name: 'Request one-time link command' }));
    expect(await screen.findByText(COMMAND)).toBeTruthy();
    expect(copy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Copy command' }));
    await waitFor(() => expect(copy).toHaveBeenCalledTimes(1));
    expect(copy).toHaveBeenCalledWith(COMMAND);
    expect(screen.getByText(/Clear your clipboard after sending/)).toBeTruthy();
  });
});
