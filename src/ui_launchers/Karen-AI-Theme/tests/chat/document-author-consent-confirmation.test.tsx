import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DocumentAuthorConsentConfirmation } from '@/components/consent/DocumentAuthorConsentConfirmation';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ apiClient: api }));

const approvalId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const preview = {
  approval_id: approvalId,
  status: 'pending',
  profile_id: '11111111-2222-3333-4444-555555555555',
  artifact_id: '11111111-2222-3333-4444-666666666666',
  source_sha256: 'a'.repeat(64),
  analysis_allowed: true,
  style_use_allowed: false,
  expires_at: '2090-12-31T12:00:00Z',
  approval_expires_at: '2090-12-31T11:00:00Z',
};

describe('first-party document author confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ ...preview });
    api.post.mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/issue')
        ? {
            approval_id: approvalId,
            status: 'issued',
            receipt_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
          }
        : { approval_id: approvalId, status: 'approved' },
    ));
  });

  it('requires author review and explicit checkbox before confirmation', async () => {
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText(preview.artifact_id)).toBeTruthy();
    expect(screen.getByText(preview.source_sha256)).toBeTruthy();
    expect(screen.getByText('Not allowed')).toBeTruthy();

    const submit = screen.getByRole('button', { name: 'Confirm author consent' });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    expect(api.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('checkbox'));
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/api/approvals/document-consent/' + approvalId + '/confirm',
        { confirmed: true },
      );
    });
    expect(await screen.findByText(/Document-consent receipt issued/)).toBeTruthy();
    expect(screen.getByText(/Verified receipt ID/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/issue',
      undefined,
      {},
    );
    expect(screen.queryByRole('button', { name: 'Confirm author consent' })).toBeNull();
  });

  it('does not submit if canonical backend preview cannot be verified', async () => {
    api.get.mockResolvedValue({ ...preview, source_sha256: 'forged' });
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not treat a denied API confirmation as success', async () => {
    api.post.mockRejectedValue(new Error('403'));
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    await screen.findByText(preview.artifact_id);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm author consent' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByText(/Author approval recorded/)).toBeNull();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('keeps approval truthful when receipt issuance fails and supports retry', async () => {
    let issues = 0;
    api.post.mockImplementation((url: string) => {
      if (url.endsWith('/confirm')) {
        return Promise.resolve({ approval_id: approvalId, status: 'approved' });
      }
      issues += 1;
      if (issues === 1) return Promise.reject(new Error('database unavailable'));
      return Promise.resolve({
        approval_id: approvalId,
        status: 'issued',
        receipt_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      });
    });
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    await screen.findByText(preview.artifact_id);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm author consent' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText(/No document-consent receipt has been verified/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry receipt issuance' }));
    expect(await screen.findByText(/Verified receipt ID/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(3);
  });

  it('does not display pending confirmation for a decided approval', async () => {
    api.get.mockResolvedValue({ ...preview, status: 'approved' });
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText('This author decision is already approved.')).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not send an invalid approval id', async () => {
    render(<DocumentAuthorConsentConfirmation approvalId="not-a-uuid" />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
