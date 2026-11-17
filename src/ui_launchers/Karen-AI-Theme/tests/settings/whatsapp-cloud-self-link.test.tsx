import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import WhatsAppCloudSelfLink from '@/components/settings/WhatsAppCloudSelfLink';
import { apiClient, ApiError } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  apiClient: { post: vi.fn() },
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

function enterConnection(value = ID) {
  fireEvent.change(screen.getByLabelText('Operator-provided connection ID'), {
    target: { value },
  });
}

beforeEach(() => {
  vi.mocked(apiClient.post).mockResolvedValue(challenge);
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
