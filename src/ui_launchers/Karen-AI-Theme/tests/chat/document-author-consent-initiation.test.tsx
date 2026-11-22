import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DocumentAuthorConsentInitiation } from '@/components/consent/DocumentAuthorConsentInitiation';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const navigate = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('@/lib/api', () => ({ apiClient: api }));
vi.mock('next/navigation', () => ({
  useRouter: () => navigate,
}));

const documentId = '11111111-2222-3333-4444-666666666666';
const profileId = '11111111-2222-3333-4444-555555555555';
const approvalId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const document = {
  id: documentId,
  kind: 'document',
  filename: 'author-original.txt',
  mime_type: 'text/plain',
  size_bytes: 48,
  sha256: 'a'.repeat(64),
  deleted_at: null,
};

describe('document author source initiation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue([document]);
    api.post.mockResolvedValue({
      approval_id: approvalId,
      status: 'pending',
      intent: 'writing_style.document_consent.issue',
    });
  });

  it('does not submit without a server-listed source and profile', async () => {
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    expect(api.get).toHaveBeenCalledWith('/api/artifacts/');
    const button = screen.getByRole('button', { name: 'Continue to author review' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Existing draft writing-style profile ID' }),
      { target: { value: profileId } },
    );
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/api/approvals/document-consent/initiate',
        {
          profile_id: profileId,
          artifact_id: documentId,
          style_use_allowed: false,
        },
      );
    });
    expect(navigate.push).toHaveBeenCalledWith(
      '/approvals/document-consent/' + approvalId,
    );
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('submits only an explicit requested use Boolean, never scope metadata', async () => {
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Existing draft writing-style profile ID' }),
      { target: { value: profileId } },
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Continue to author review' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toEqual({
      profile_id: profileId,
      artifact_id: documentId,
      style_use_allowed: true,
    });
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('source_sha256');
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('tenant_id');
    expect(api.post.mock.calls[0][1]).not.toHaveProperty('session_id');
  });

  it('does not offer altered, deleted, oversized or research artifacts', async () => {
    api.get.mockResolvedValue([
      { ...document, id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', kind: 'search_article' },
      { ...document, id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', deleted_at: '2026-01-01' },
      { ...document, id: 'cccccccc-cccc-cccc-cccc-cccccccccccc', size_bytes: 65537 },
      { ...document, id: 'dddddddd-dddd-dddd-dddd-dddddddddddd', sha256: '' },
    ]);
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/No eligible documents/)).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Your document' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Continue to author review' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not navigate or claim consent when initiation is denied', async () => {
    api.post.mockRejectedValue(new Error('403'));
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Existing draft writing-style profile ID' }),
      { target: { value: profileId } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Continue to author review' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(navigate.push).not.toHaveBeenCalled();
  });

  it('does not navigate on a malformed or nonpending backend response', async () => {
    api.post.mockResolvedValue({
      approval_id: approvalId,
      status: 'issued',
      intent: 'writing_style.document_consent.issue',
    });
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Existing draft writing-style profile ID' }),
      { target: { value: profileId } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Continue to author review' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(navigate.push).not.toHaveBeenCalled();
  });
});
