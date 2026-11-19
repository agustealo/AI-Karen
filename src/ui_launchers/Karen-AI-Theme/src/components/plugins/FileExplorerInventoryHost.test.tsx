// @vitest-environment jsdom
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FileExplorerInventoryHost } from './FileExplorerInventoryHost';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ apiClient: { get: mocks.get } }));
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
