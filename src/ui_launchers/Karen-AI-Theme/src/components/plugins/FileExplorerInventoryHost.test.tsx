// @vitest-environment jsdom
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FileExplorerInventoryHost } from './FileExplorerInventoryHost';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ apiClient: { get: mocks.get, post: mocks.post } }));
vi.mock('@/lib/useAuth', () => ({ useAuth: mocks.useAuth }));

const SHA = 'a'.repeat(64);
const FILE_A = '44444444-4444-4444-8444-000000000001';
const FILE_B = '44444444-4444-4444-8444-000000000002';

function response(id: string, hasMore = false, cursor: string | null = null) {
  return {
    items: [{
      source_id: id,
      parent_id: null,
      kind: 'file',
      name: id === FILE_A ? 'alpha.txt' : 'beta.txt',
      revision: SHA,
      size_bytes: 11,
      sha256: SHA,
    }],
    has_more: hasMore,
    next_cursor: cursor,
    inventory_semantics: 'owner_metadata_page_not_live_acl',
    request_id: 'request-1',
    correlation_id: 'corr-1',
  };
}

function auth(userId = 'owner-one') {
  return {
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: userId,
      tenant_id: 'tenant-one',
      roles: ['user'],
      permissions: ['data:read'],
    },
  };
}

function Consumer() {
  return (
    <FileExplorerInventoryHost>
      {(props) => (
        <section>
          <output data-testid="authorized">{String(props.authorized)}</output>
          <output data-testid="page">{props.items.map((item) => item.name).join(',')}</output>
          <output data-testid="loading">{String(props.loading)}</output>
          <output data-testid="error">{props.error}</output>
          <output data-testid="key">{props.pageKey}</output>
          <output data-testid="selection">{props.selectedSourceIds.join(',')}</output>
          <button type="button" onClick={props.onRefresh}>Refresh</button>
          <button type="button" onClick={() => props.onNextPage(props.nextCursor || '')}>Next</button>
          <button type="button" onClick={() => props.onSelect([{
            source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'file',
          }])}>Select A</button>
          <button type="button" onClick={() => props.onSelect([{
            source_id: FILE_A, revision: 'b'.repeat(64), sha256: SHA, kind: 'file',
          }])}>Stale revision</button>
          <button type="button" onClick={() => props.onSelect([{
            source_id: FILE_A, revision: SHA, sha256: 'b'.repeat(64), kind: 'file',
          }])}>Forged hash</button>
          <button type="button" onClick={() => props.onSelect([{
            source_id: FILE_B, revision: SHA, sha256: SHA, kind: 'file',
          }])}>Foreign ID</button>
          <button type="button" onClick={() => props.onSelect([{
            source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'folder',
          }])}>Forged kind</button>
          <button type="button" onClick={() => props.onSelect([
            { source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'file' },
            { source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'file' },
          ])}>Duplicate ID</button>
          <button type="button" onClick={() => props.onSelect([
            { source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'file' },
            { source_id: FILE_B, revision: SHA, sha256: SHA, kind: 'file' },
          ])}>Mixed forged list</button>
        </section>
      )}
    </FileExplorerInventoryHost>
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.useAuth.mockReset();
  mocks.useAuth.mockReturnValue(auth());
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('File Explorer authenticated UI host', () => {
  it('fetches only authenticated owner metadata and advances exact returned cursor', async () => {
    mocks.get
      .mockResolvedValueOnce(response(FILE_A, true, 'owner-scoped-cursor'))
      .mockResolvedValueOnce(response(FILE_B));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    expect(screen.getByTestId('authorized').textContent).toBe('true');
    expect(mocks.get).toHaveBeenNthCalledWith(1, '/api/plugins/file-explorer/inventory?limit=100');

    fireEvent.click(screen.getByText('Select A'));
    expect(screen.getByTestId('selection').textContent).toBe(FILE_A);
    const firstKey = screen.getByTestId('key').textContent;

    fireEvent.click(screen.getByText('Next'));
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('beta.txt'));
    expect(mocks.get).toHaveBeenNthCalledWith(
      2, '/api/plugins/file-explorer/inventory?limit=100&cursor=owner-scoped-cursor',
    );
    expect(screen.getByTestId('selection').textContent).toBe('');
    expect(screen.getByTestId('key').textContent).not.toBe(firstKey);
  });

  it('rejects stale and forged selection receipts without partially accepting IDs', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    for (const label of [
      'Stale revision', 'Forged hash', 'Foreign ID', 'Forged kind',
      'Duplicate ID', 'Mixed forged list',
    ]) {
      fireEvent.click(screen.getByText('Select A'));
      expect(screen.getByTestId('selection').textContent).toBe(FILE_A);
      fireEvent.click(screen.getByText(label));
      expect(screen.getByTestId('selection').textContent).toBe('');
    }
  });

  it('clears selection on refresh and requests an authorized first page', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    expect(screen.getByTestId('selection').textContent).toBe(FILE_A);
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    expect(screen.getByTestId('selection').textContent).toBe('');
  });

  it('rejects an old principal response and does not display cross-user inventory', async () => {
    let resolveFirst!: (value: unknown) => void;
    mocks.get
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(response(FILE_B));
    const view = render(<Consumer />);
    expect(mocks.get).toHaveBeenCalledTimes(1);

    mocks.useAuth.mockReturnValue(auth('owner-two'));
    view.rerender(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('beta.txt'));

    await act(async () => resolveFirst(response(FILE_A)));
    expect(screen.getByTestId('authorized').textContent).toBe('true');
    expect(screen.getByTestId('page').textContent).toBe('beta.txt');
  });

  it('denies unverified pages instead of inventing an empty inventory', async () => {
    mocks.get.mockResolvedValue({
      ...response(FILE_A),
      has_more: true,
      next_cursor: null,
    });
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authorized').textContent).toBe('false');
    expect(screen.getByTestId('error').textContent).toContain('Invalid file inventory response');
    expect(screen.getByTestId('page').textContent).toBe('');
  });

  it('never fetches inventory for signed-out users', async () => {
    mocks.useAuth.mockReturnValue({
      user: null, isAuthenticated: false, isLoading: false,
    });
    render(<Consumer />);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(screen.getByTestId('authorized').textContent).toBe('false');
  });
});


function analyzed(id = FILE_A, revision = SHA) {
  return {
    operation: 'analyze',
    persisted: false,
    documents: [{
      id,
      name: 'alpha.txt',
      sha256: revision,
      characters: 24,
      top_terms: [{ term: 'vendor', count: 2 }],
    }],
  };
}

describe('File Explorer to Content Intelligence handoff', () => {
  it('submits only the selected source id and revision, then displays verified analysis', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockResolvedValue(analyzed());
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();

    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText('vendor (2)')).toBeTruthy());

    expect(mocks.post).toHaveBeenCalledTimes(1);
    const [path, payload, options] = mocks.post.mock.calls[0];
    expect(path).toBe('/api/plugins/content-intelligence/owner-sources');
    expect(payload).toEqual({
      operation: 'analyze',
      references: [{ source_id: FILE_A, revision: SHA }],
    });
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(screen.getByText(/Lexical analysis of 1 authorized file/)).toBeTruthy();
  });

  it('rejects a response whose digest does not match the current selection', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockResolvedValue(analyzed(FILE_A, 'b'.repeat(64)));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText(/Analysis is unavailable or access was denied/)).toBeTruthy());
    expect(screen.queryByText('vendor (2)')).toBeNull();
  });

  it('does not expose an old analysis after refresh changes page generation', async () => {
    let resolveAnalysis!: (value: unknown) => void;
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockImplementation(() => new Promise((resolve) => {
      resolveAnalysis = resolve;
    }));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Refresh'));
    await act(async () => resolveAnalysis(analyzed()));
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    expect(screen.queryByText('vendor (2)')).toBeNull();
    expect(screen.queryByRole('region', { name: 'Verified analysis results' })).toBeNull();
  });

  it('fails closed when the backend denies authorization', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockRejectedValue(new Error('Forbidden with private details'));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText(/Analysis is unavailable or access was denied/)).toBeTruthy());
    expect(screen.queryByText(/private details/)).toBeNull();
  });

  it('never initiates content analysis for an unauthenticated principal', async () => {
    mocks.useAuth.mockReturnValue({ user: null, isAuthenticated: false, isLoading: false });
    render(<Consumer />);
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
