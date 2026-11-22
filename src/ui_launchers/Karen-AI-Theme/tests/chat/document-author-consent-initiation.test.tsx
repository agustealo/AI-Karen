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
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?') ? { items: [document], has_more: false, next_cursor: null } : [{
        profile_id: profileId, label: 'My style', kind: 'personal',
      }],
    ));
    api.post.mockResolvedValue({
      approval_id: approvalId,
      status: 'pending',
      intent: 'writing_style.document_consent.issue',
    });
  });

  it('does not submit without a server-listed source and profile', async () => {
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    expect(api.get).toHaveBeenCalledWith('/api/artifacts/owner-page?limit=100');
    expect(api.get).toHaveBeenCalledWith('/api/approvals/document-consent/profiles');
    const button = screen.getByRole('button', { name: 'Continue to author review' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Your draft writing-style profile' }),
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
      screen.getByRole('combobox', { name: 'Your draft writing-style profile' }),
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
    api.get.mockImplementation((url: string) => Promise.resolve(url.startsWith('/api/artifacts/owner-page?') ? { items: [
      { ...document, id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', kind: 'search_article' },
      { ...document, id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', deleted_at: '2026-01-01' },
      { ...document, id: 'cccccccc-cccc-cccc-cccc-cccccccccccc', size_bytes: 65537 },
      { ...document, id: 'dddddddd-dddd-dddd-dddd-dddddddddddd', sha256: '' },
    ], has_more: false, next_cursor: null } : [{ profile_id: profileId, label: 'My style', kind: 'personal' }]));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/No eligible documents/)).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Your document' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Continue to author review' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('only offers filenames compatible with canonical bounded storage reads', async () => {
    const validMarkdown = { ...document, id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', filename: 'author-notes.MD' };
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?')
        ? { items: [
          { ...document, filename: 'author original.txt' },
          { ...document, id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', filename: '../source.txt' },
          { ...document, id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', filename: 'plain.pdf' },
          { ...document, id: 'cccccccc-cccc-cccc-cccc-cccccccccccc', filename: 'file.txt/other' },
          { ...document, id: 'dddddddd-dddd-dddd-dddd-dddddddddddd', filename: 'x'.repeat(157) + '.txt' },
          validMarkdown,
          null,
        ], has_more: false, next_cursor: null }
        : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/author-notes.MD/)).toBeTruthy();
    const choice = screen.getByRole('combobox', { name: 'Your document' }) as HTMLSelectElement;
    expect(Array.from(choice.options).map((option) => option.value)).toEqual(['', validMarkdown.id]);
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
      screen.getByRole('combobox', { name: 'Your draft writing-style profile' }),
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
      screen.getByRole('combobox', { name: 'Your draft writing-style profile' }),
      { target: { value: profileId } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Continue to author review' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(navigate.push).not.toHaveBeenCalled();
  });
  it('does not submit when the authenticated draft inventory is empty', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?')
        ? { items: [document], has_more: false, next_cursor: null }
        : [],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/No eligible author-owned draft profiles/)).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Your draft writing-style profile' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Continue to author review' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('pages through owned metadata without an unlisted artifact ID shortcut', async () => {
    const later = { ...document, id: '22222222-2222-2222-2222-222222222222', filename: 'later.txt' };
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.includes('cursor=owned-next')
        ? { items: [later], has_more: false, next_cursor: null }
        : url.startsWith('/api/artifacts/owner-page?')
          ? { items: [document], has_more: true, next_cursor: 'owned-next' }
          : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/author-original.txt/)).toBeTruthy();
    const inventory = screen.getByRole('region', { name: 'Initiate document author consent' });
    expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('1');
    expect(screen.queryByText(/later.txt/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Load more owned documents' }));
    expect(await screen.findByText(/later.txt/)).toBeTruthy();
    await waitFor(() => expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('2'));
    expect(api.get).toHaveBeenCalledWith(
      '/api/artifacts/owner-page?limit=100&cursor=owned-next',
    );
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: later.id },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Your draft writing-style profile' }), {
      target: { value: profileId },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to author review' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/approvals/document-consent/initiate',
      { profile_id: profileId, artifact_id: later.id, style_use_allowed: false },
    ));
  });

  it('fails closed on malformed owner-page metadata', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?')
        ? { items: [document], has_more: true, next_cursor: null }
        : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Your document' })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not count or admit a malformed continuation response', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.includes('cursor=next-page')
        ? { items: [document], has_more: false, next_cursor: 'unexpected' }
        : url.startsWith('/api/artifacts/owner-page?')
          ? { items: [document], has_more: true, next_cursor: 'next-page' }
          : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    const inventory = screen.getByRole('region', { name: 'Initiate document author consent' });
    expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('1');
    fireEvent.click(screen.getByRole('button', { name: 'Load more owned documents' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('1');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not accept an empty continuation page or repeat its cursor', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.includes('cursor=next-page')
        ? { items: [], has_more: true, next_cursor: 'next-page' }
        : url.startsWith('/api/artifacts/owner-page?')
          ? { items: [document], has_more: true, next_cursor: 'next-page' }
          : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    const inventory = screen.getByRole('region', { name: 'Initiate document author consent' });
    fireEvent.click(screen.getByRole('button', { name: 'Load more owned documents' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('1');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects an over-limit initial page rather than presenting it as verified', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?')
        ? { items: Array.from({ length: 101 }, () => document), has_more: false, next_cursor: null }
        : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    const inventory = screen.getByRole('region', { name: 'Initiate document author consent' });
    expect(inventory.getAttribute('data-owner-pages-loaded')).toBe('0');
    expect(screen.queryByRole('combobox', { name: 'Your document' })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('filters malformed draft entries while preserving a real eligible profile', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.startsWith('/api/artifacts/owner-page?')
        ? { items: [document], has_more: false, next_cursor: null }
        : [null, false, {}, { profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    expect(await screen.findByText(/author-original.txt/)).toBeTruthy();
    const draftChoice = screen.getByRole('combobox', {
      name: 'Your draft writing-style profile',
    }) as HTMLSelectElement;
    expect(Array.from(draftChoice.options).map((option) => option.value))
      .toEqual(['', profileId]);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('blocks consent initiation after a malformed continuation response', async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(
      url.includes('cursor=next-page')
        ? { items: [document], has_more: false, next_cursor: 'invalid-terminal-cursor' }
        : url.startsWith('/api/artifacts/owner-page?')
          ? { items: [document], has_more: true, next_cursor: 'next-page' }
          : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
    ));
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Your draft writing-style profile' }), {
      target: { value: profileId },
    });
    const initiate = screen.getByRole('button', { name: 'Continue to author review' }) as HTMLButtonElement;
    expect(initiate.disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Load more owned documents' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(initiate.disabled).toBe(true);
    fireEvent.click(initiate);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('disables author initiation during an unresolved owner-page request', async () => {
    let resolveNextPage: ((value: unknown) => void) | undefined;
    api.get.mockImplementation((url: string) => (
      url.includes('cursor=next-page')
        ? new Promise((resolve) => { resolveNextPage = resolve; })
        : Promise.resolve(
            url.startsWith('/api/artifacts/owner-page?')
              ? { items: [document], has_more: true, next_cursor: 'next-page' }
              : [{ profile_id: profileId, label: 'My style', kind: 'personal' }],
          )
    ));
    render(<DocumentAuthorConsentInitiation />);
    await screen.findByText(/author-original.txt/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Your document' }), {
      target: { value: documentId },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Your draft writing-style profile' }), {
      target: { value: profileId },
    });
    const initiate = screen.getByRole('button', { name: 'Continue to author review' }) as HTMLButtonElement;
    expect(initiate.disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Load more owned documents' }));
    expect(screen.getByRole('button', { name: 'Loading documents…' })).toBeTruthy();
    expect(initiate.disabled).toBe(true);
    fireEvent.click(initiate);
    expect(api.post).not.toHaveBeenCalled();
    resolveNextPage?.({ items: [], has_more: false, next_cursor: null });
    await waitFor(() => expect(initiate.disabled).toBe(false));
    expect(api.post).not.toHaveBeenCalled();
  });

});
