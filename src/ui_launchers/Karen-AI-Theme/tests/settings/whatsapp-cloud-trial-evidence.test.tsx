import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import WhatsAppCloudTrialEvidence from '@/components/settings/WhatsAppCloudTrialEvidence';
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

const CONNECTION = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
const EVENT = 'wamid.inbound-trial-1';
const ENDPOINT = `/api/channels/operator/whatsapp/connections/${CONNECTION}/trial-evidence`;

const evidence = {
  connection_revision: 4,
  current_connection_revision: 4,
  connection_enabled: true,
  inbox_id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
  correlation_id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
  inbox_status: 'completed',
  binding_currently_active: true,
  outbound_delivery_id: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
  outbound_status: 'read',
  outbound_provider_message_sha256: 'a'.repeat(64),
  provider_receipt_states: ['delivered', 'read'],
  evidence_basis: 'host_persisted_lineage_only',
  meta_origin_independently_verified: false,
  consumer_certified: false,
};

function enterEvent(value = EVENT) {
  fireEvent.change(screen.getByLabelText('Inbound WhatsApp message ID'), {
    target: { value },
  });
}

beforeEach(() => {
  vi.mocked(apiClient.post).mockResolvedValue(evidence);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe('WhatsApp Cloud operator trial evidence', () => {
  it('requires explicit valid test message and uses only the authenticated inspection API', async () => {
    render(<WhatsAppCloudTrialEvidence connectionId={CONNECTION} />);
    const button = screen.getByRole('button', { name: 'Inspect persisted evidence' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    enterEvent('bad/invalid');
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(apiClient.post).not.toHaveBeenCalled();
    enterEvent();
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(
      ENDPOINT, { external_event_id: EVENT },
    ));
    expect(await screen.findByText(/Host-persisted history only/)).toBeTruthy();
    expect(screen.getByText(/Independent Meta-origin verification/)).toBeTruthy();
    expect(screen.getByText('delivered, read')).toBeTruthy();
    expect(screen.getByText(/Correlation ID/)).toBeTruthy();
    expect(screen.queryByText(/Meta subscription verified/)).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it('never confuses a pending inbox with ChatRuntime or provider receipts', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      ...evidence,
      inbox_status: 'pending',
      binding_currently_active: false,
      outbound_delivery_id: null,
      outbound_status: null,
      outbound_provider_message_sha256: null,
      provider_receipt_states: [],
    });
    render(<WhatsAppCloudTrialEvidence connectionId={CONNECTION} />);
    enterEvent();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect persisted evidence' }));
    expect(await screen.findByText(/No durable reply staged/)).toBeTruthy();
    expect(screen.getByText(/None recorded/)).toBeTruthy();
    expect(screen.getByText(/Not currently active/)).toBeTruthy();
  });

  it.each([
    { ...evidence, meta_origin_independently_verified: true },
    { ...evidence, consumer_certified: true },
    { ...evidence, outbound_status: 'provider-guaranteed-success' },
    { ...evidence, inbound_message_text: 'private text' },
    { ...evidence, provider_receipt_states: ['delivered', 'arbitrary'] },
    { ...evidence, provider_receipt_states: ['read', 'read'] },
    { ...evidence, outbound_provider_message_sha256: 'wamid.raw-id' },
    { ...evidence, connection_revision: 0 },
    { ...evidence, inbox_id: 'not-a-uuid' },
    { ...evidence, outbound_status: 'read', inbox_status: 'processing' },
  ])('rejects forged or contradictory evidence projections', async (forged) => {
    vi.mocked(apiClient.post).mockResolvedValue(forged);
    render(<WhatsAppCloudTrialEvidence connectionId={CONNECTION} />);
    enterEvent();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect persisted evidence' }));
    expect((await screen.findByRole('alert')).textContent).toContain(
      'could not verify the trial evidence',
    );
    expect(screen.queryByText(/Host-persisted history only/)).toBeNull();
    expect(screen.queryByText(/provider-guaranteed-success/)).toBeNull();
    expect(screen.queryByText(/private text/)).toBeNull();
  });

  it('redacts backend errors and does not replay inspection by itself', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(
      403, 'vault://private and raw provider secrets',
    ));
    render(<WhatsAppCloudTrialEvidence connectionId={CONNECTION} />);
    enterEvent();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect persisted evidence' }));
    expect((await screen.findByRole('alert')).textContent)
      .toContain('cannot inspect this connection');
    expect(screen.queryByText(/vault:\/\/private/)).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it('erases the prior view when the event changes', async () => {
    render(<WhatsAppCloudTrialEvidence connectionId={CONNECTION} />);
    enterEvent();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect persisted evidence' }));
    expect(await screen.findByText(/Host-persisted history only/)).toBeTruthy();
    enterEvent('wamid.another-event');
    expect(screen.queryByText(/Host-persisted history only/)).toBeNull();
  });

  it('does not trust a forged connection ID from the caller', async () => {
    render(<WhatsAppCloudTrialEvidence connectionId={'not-a-uuid'} />);
    enterEvent();
    const button = screen.getByRole('button', { name: 'Inspect persisted evidence' });
    fireEvent.click(button);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
