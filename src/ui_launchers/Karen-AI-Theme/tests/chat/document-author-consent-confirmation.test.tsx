import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  source_name: 'author-original.txt',
  source_bytes: 1024,
  source_mime_type: 'text/plain',
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
    expect(screen.getByText('author-original.txt')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Initiate another document review' }).getAttribute('href'))
      .toBe('/approvals/document-consent/new');
    expect(screen.getByText('1024 bytes (text/plain)')).toBeTruthy();
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
    fireEvent.click(screen.getByRole('button', { name: 'Issue approved consent receipt' }));
    expect(await screen.findByText(/Verified receipt ID/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/issue',
    );
  });

  it('recovers a receipt from a consumed approval without issuing again', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/receipt')
        ? {
            approval_id: approvalId, status: 'issued',
            receipt_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
          }
        : { ...preview, status: 'consumed' },
    ));
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText(/Verified receipt ID/)).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/receipt',
    );
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('checkbox', { name: /I authored this document/ })).toBeNull();
  });

  it('denies review when the server has no valid source identity', async () => {
    api.get.mockResolvedValue({ ...preview, source_name: '' });
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not send an invalid approval id', async () => {
    render(<DocumentAuthorConsentConfirmation approvalId="not-a-uuid" />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('requires a separate revocation gesture and only acknowledges backend finality', async () => {
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    await screen.findByText(preview.artifact_id);
    fireEvent.click(screen.getByRole('checkbox', { name: /I authored this document/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm author consent' }));
    expect(await screen.findByText(/Document-consent receipt issued/)).toBeTruthy();

    const revoke = screen.getByRole('button', { name: 'Revoke document consent' });
    expect((revoke as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(revoke);
    expect(api.post).not.toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/revoke',
      { confirmed: true },
    );
    api.post.mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/revoke')
        ? { approval_id: approvalId, status: 'revoked' }
        : { approval_id: approvalId, status: 'approved' },
    ));
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'Confirm revoke document consent',
    }));
    fireEvent.click(revoke);
    expect(await screen.findByText(/Document consent revocation recorded/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/revoke',
      { confirmed: true },
    );
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry receipt issuance' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Issue approved consent receipt' })).toBeNull();
  });

  it('does not claim revoked consent on failed backend revocation', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/receipt')
        ? { approval_id: approvalId, status: 'issued', receipt_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' }
        : { ...preview, status: 'consumed' },
    ));
    api.post.mockRejectedValue(new Error('409'));
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText(/Verified receipt ID:/)).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'Confirm revoke document consent',
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Revoke document consent' }));
    expect(await screen.findByText(/Revocation was not confirmed/)).toBeTruthy();
    expect(screen.queryByText(/Document consent revocation recorded/)).toBeNull();
    expect(screen.getByText(/Verified receipt ID:/)).toBeTruthy();
  });


  it('clears a stale receipt after an uncertain revocation and failed recovery', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/receipt')
        ? { approval_id: approvalId, status: 'issued', receipt_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' }
        : { ...preview, status: 'consumed' },
    ));
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText(/Verified receipt ID:/)).toBeTruthy();
    api.post.mockRejectedValue(new Error('lost response'));
    api.get.mockRejectedValue(new Error('receipt now unavailable'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Confirm revoke document consent' }));
    fireEvent.click(screen.getByRole('button', { name: 'Revoke document consent' }));
    expect(await screen.findByText(/No current consent receipt was recovered/)).toBeTruthy();
    expect(screen.queryByText(/Document consent revocation recorded/)).toBeNull();
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
  });


  it('offers author-scoped revocation after token rotation without source recovery', async () => {
    api.get.mockImplementation((url: string) => (
      url.endsWith('/revoke-review')
        ? Promise.resolve({
            approval_id: approvalId,
            status: 'consumed',
            profile_id: preview.profile_id,
            artifact_id: preview.artifact_id,
            source_sha256: preview.source_sha256,
          })
        : Promise.reject(new Error('original token expired or source deleted'))
    ));
    api.post.mockResolvedValue({ approval_id: approvalId, status: 'revoked' });

    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByText(/Your current session can request/)).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/revoke-review',
    );
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Confirm author consent' })).toBeNull();

    const revoke = screen.getByRole('button', { name: 'Revoke document consent' });
    expect((revoke as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'Confirm revoke document consent',
    }));
    fireEvent.click(revoke);
    expect(await screen.findByText(/Document consent revocation recorded/)).toBeTruthy();
    expect(api.post).toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/revoke',
      { confirmed: true },
    );
  });

  it('fails closed if the independent revocation metadata is malformed', async () => {
    api.get.mockImplementation((url: string) => (
      url.endsWith('/revoke-review')
        ? Promise.resolve({
            approval_id: approvalId, status: 'consumed',
            profile_id: preview.profile_id,
            artifact_id: preview.artifact_id,
            source_sha256: 'invalid',
          })
        : Promise.reject(new Error('unavailable'))
    ));
    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Revoke document consent' })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });


  it('does not attach an old consumed approval receipt to a newly opened approval', async () => {
    const nextApprovalId = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff';
    const historicalReceipt = 'cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa';
    let resolveOldReceipt: ((record: unknown) => void) | undefined;
    api.get.mockImplementation((url: string) => {
      if (url === '/api/approvals/document-consent/' + approvalId) {
        return Promise.resolve({ ...preview, status: 'consumed' });
      }
      if (url === '/api/approvals/document-consent/' + approvalId + '/receipt') {
        return new Promise((resolve) => { resolveOldReceipt = resolve; });
      }
      if (url === '/api/approvals/document-consent/' + nextApprovalId) {
        return Promise.resolve({ ...preview, approval_id: nextApprovalId, status: 'pending' });
      }
      return Promise.reject(new Error('unexpected approval'));
    });

    const view = render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    await waitFor(() => expect(resolveOldReceipt).toBeDefined());

    view.rerender(<DocumentAuthorConsentConfirmation approvalId={nextApprovalId} />);
    expect(await screen.findByRole('checkbox', {
      name: /I authored this document/,
    })).toBeTruthy();

    await act(async () => {
      resolveOldReceipt?.({
        approval_id: approvalId, receipt_id: historicalReceipt, status: 'issued',
      });
    });
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Revoke document consent' })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('discards an older receipt recheck completed after confirmed revocation', async () => {
    const receipt = {
      approval_id: approvalId,
      receipt_id: 'dddddddd-eeee-ffff-aaaa-bbbbbbbbbbbb',
      status: 'issued',
    };
    let resolveInitialReceipt: ((record: unknown) => void) | undefined;
    let reads = 0;
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/receipt')) {
        reads += 1;
        return reads === 1
          ? new Promise((resolve) => { resolveInitialReceipt = resolve; })
          : Promise.resolve(receipt);
      }
      return Promise.resolve({ ...preview, status: 'consumed' });
    });
    api.post.mockResolvedValue({ approval_id: approvalId, status: 'revoked' });

    render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    expect(await screen.findByRole('button', {
      name: 'Recheck current consent receipt',
    })).toBeTruthy();
    await waitFor(() => expect(resolveInitialReceipt).toBeDefined());

    fireEvent.click(screen.getByRole('button', {
      name: 'Recheck current consent receipt',
    }));
    expect(await screen.findByText(/Verified receipt ID:/)).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', {
      name: 'Confirm revoke document consent',
    }));
    fireEvent.click(screen.getByRole('button', {
      name: 'Revoke document consent',
    }));
    expect(await screen.findByText(/Document consent revocation recorded/)).toBeTruthy();

    await act(async () => { resolveInitialReceipt?.(receipt); });
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Revoke document consent' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Recheck current consent receipt' })).toBeNull();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('keeps a new approval isolated from a delayed former confirmation', async () => {
    const nextApprovalId = 'cccccccc-dddd-eeee-ffff-111111111111';
    let resolveOldConfirm: ((record: unknown) => void) | undefined;
    api.get.mockImplementation((url: string) => Promise.resolve({
      ...preview,
      approval_id: url.endsWith(nextApprovalId) ? nextApprovalId : approvalId,
    }));
    api.post.mockImplementation((url: string) => (
      url.endsWith('/confirm')
        ? new Promise((resolve) => { resolveOldConfirm = resolve; })
        : Promise.reject(new Error('unexpected issuance'))
    ));

    const view = render(<DocumentAuthorConsentConfirmation approvalId={approvalId} />);
    await screen.findByText(preview.artifact_id);
    fireEvent.click(screen.getByRole('checkbox', {
      name: /I authored this document/,
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm author consent' }));
    await waitFor(() => expect(resolveOldConfirm).toBeDefined());

    view.rerender(<DocumentAuthorConsentConfirmation approvalId={nextApprovalId} />);
    expect(await screen.findByRole('checkbox', {
      name: /I authored this document/,
    })).toBeTruthy();

    await act(async () => {
      resolveOldConfirm?.({ approval_id: approvalId, status: 'approved' });
    });
    expect(screen.queryByText(/Author approval recorded/)).toBeNull();
    expect(screen.queryByText(/Verified receipt ID:/)).toBeNull();
    expect(screen.getByRole('button', {
      name: 'Confirm author consent',
    })).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalledWith(
      '/api/approvals/document-consent/' + approvalId + '/issue',
    );
  });

});
