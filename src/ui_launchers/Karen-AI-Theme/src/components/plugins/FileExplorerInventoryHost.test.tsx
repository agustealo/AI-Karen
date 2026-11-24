// @vitest-environment jsdom
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FileExplorerInventoryHost, type InventoryConsumer } from './FileExplorerInventoryHost';

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

function Consumer({ mode, consumer }: { mode?: 'analysis' | 'selection'; consumer?: InventoryConsumer } = {}) {
  return (
    <FileExplorerInventoryHost mode={mode} consumer={consumer}>
      {(props) => (
        <section>
          <output data-testid="authorized">{String(props.authorized)}</output>
          <output data-testid="page">{props.items.map((item) => item.name).join(',')}</output>
          <output data-testid="loading">{String(props.loading)}</output>
          <output data-testid="error">{props.error}</output>
          <output data-testid="key">{props.pageKey}</output>
          <output data-testid="selection">{props.selectedSourceIds.join(',')}</output>
          <button type="button" onClick={props.onRefresh}>Refresh</button>
          <button type="button" onClick={() => {
            const current = props.items[0];
            if (current) {
              props.onSelect([{
                source_id: current.source_id,
                revision: current.revision,
                sha256: current.sha256,
                kind: current.kind,
              }]);
            }
          }}>Select current</button>
          <button type="button" onClick={() => props.onSelect(props.items.map((item) => ({
            source_id: item.source_id, revision: item.revision, sha256: item.sha256, kind: item.kind,
          })))}>Select all current</button>
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

describe('File Explorer selection-only host', () => {
  it('validates selection without mounting or invoking Content Intelligence', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<Consumer mode="selection" />);
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select A'));
    expect(screen.getByTestId('selection').textContent).toBe(FILE_A);
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    fireEvent.click(screen.getByText('Forged hash'));
    expect(screen.getByTestId('selection').textContent).toBe('');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('hides previously verified inventory during authentication revalidation', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    const view = render(<Consumer mode="selection" />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    mocks.useAuth.mockReturnValue({ ...auth(), isLoading: true });
    view.rerender(<Consumer mode="selection" />);
    expect(screen.getByTestId('authorized').textContent).toBe('false');
    expect(screen.getByTestId('page').textContent).toBe('');
    expect(screen.getByTestId('selection').textContent).toBe('');
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

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

  it('reloads authoritative owner inventory after a stale revision failure and requires new selection', async () => {
    const latestSha = 'b'.repeat(64);
    const latestPage = response(FILE_A);
    latestPage.items[0].revision = latestSha;
    latestPage.items[0].sha256 = latestSha;
    mocks.get.mockResolvedValueOnce(response(FILE_A)).mockResolvedValueOnce(latestPage);
    mocks.post.mockRejectedValueOnce(new Error('private stale revision details'))
      .mockResolvedValueOnce(analyzed(FILE_A, latestSha));

    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Refresh inventory'));
    expect(screen.queryByText(/private stale revision details/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh inventory and reselect' }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    expect(screen.getByTestId('selection').textContent).toBe('');
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.post).toHaveBeenCalledTimes(1);

    // Only a fresh selection on the new authorized page can invoke analysis.
    fireEvent.click(screen.getByText('Select current'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText('vendor (2)')).toBeTruthy());
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(mocks.post.mock.calls[1][1]).toEqual({
      operation: 'analyze',
      references: [{ source_id: FILE_A, revision: latestSha }],
    });
  });

  it('can retry a transient analysis failure without fabricating an authorized result', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockRejectedValueOnce(new Error('Service unavailable'))
      .mockResolvedValueOnce(analyzed());
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Analysis is unavailable'));
    expect(screen.queryByRole('status', { name: 'Verified analysis results' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText('vendor (2)')).toBeTruthy());
    expect(mocks.post).toHaveBeenCalledTimes(2);
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
    expect(screen.queryByRole('status', { name: 'Verified analysis results' })).toBeNull();
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


describe('Content Intelligence canonical lexical token compatibility', () => {
  it('accepts valid long tokens but limits rendered content length', async () => {
    const longTerm = 'x'.repeat(512);
    mocks.get.mockResolvedValue(response(FILE_A));
    mocks.post.mockResolvedValue({
      ...analyzed(),
      documents: [{ ...analyzed().documents[0], top_terms: [{ term: longTerm, count: 1 }] }],
    });
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected files' }));
    await waitFor(() => expect(screen.getByText('x'.repeat(128) + '… (1)')).toBeTruthy());
    expect(screen.queryByText(longTerm + ' (1)')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('Content Intelligence document search', () => {
  function searchResult(revision = SHA) {
    return {
      operation: 'search', persisted: false, query: 'vendor',
      search_semantics: 'lexical_evidence_only',
      matches: [{
        document_id: FILE_A, document_name: 'alpha.txt', folder_id: null,
        sha256: revision, offset: 0, end_offset: 6, excerpt: 'vendor',
        matched_terms: ['vendor'], score: 1,
      }],
    };
  }

  async function selectSearch() {
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select A'));
    fireEvent.change(screen.getByLabelText('Operation'), { target: { value: 'search' } });
    fireEvent.change(screen.getByLabelText('Search terms'), { target: { value: 'vendor' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search selected files' }));
  }

  it('submits a bounded query and displays revision-bound passages', async () => {
    mocks.post.mockResolvedValue(searchResult());
    await selectSearch();
    await waitFor(() => expect(screen.getByRole('status', { name: 'Verified search results' })).toBeTruthy());
    expect(mocks.post.mock.calls[0][1]).toEqual({
      operation: 'search', query: 'vendor', references: [{ source_id: FILE_A, revision: SHA }],
    });
    expect(screen.getByText('vendor')).toBeTruthy();
  });

  it('rejects a substituted revision', async () => {
    mocks.post.mockResolvedValue(searchResult('b'.repeat(64)));
    await selectSearch();
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.queryByRole('status', { name: 'Verified search results' })).toBeNull();
  });

  it('discards an in-flight search when the query changes', async () => {
    let resolveSearch!: (value: unknown) => void;
    mocks.post.mockImplementation(() => new Promise((resolve) => { resolveSearch = resolve; }));
    await selectSearch();
    fireEvent.change(screen.getByLabelText('Search terms'), { target: { value: 'other' } });
    await act(async () => resolveSearch(searchResult()));
    expect(screen.queryByRole('status', { name: 'Verified search results' })).toBeNull();
    expect(mocks.post.mock.calls[0][2].signal.aborted).toBe(true);
  });
});

describe('Content Intelligence document comparison', () => {
  const rightSha = 'b'.repeat(64);
  function compared() {
    return {
      operation: 'compare', persisted: false, comparison_semantics: 'lexical_not_semantic',
      left_id: FILE_A, right_id: FILE_B, left_sha256: SHA, right_sha256: rightSha,
      shared_terms: ['vendor'], only_left: ['deposit'], only_right: ['warranty'],
      jaccard_similarity: 0.3333,
    };
  }

  async function selectCompare() {
    const page = response(FILE_A);
    page.items.push({ ...response(FILE_B).items[0], revision: rightSha, sha256: rightSha });
    mocks.get.mockResolvedValue(page);
    render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select all current'));
    fireEvent.change(screen.getByLabelText('Operation'), { target: { value: 'compare' } });
    fireEvent.change(screen.getByLabelText('Left document'), { target: { value: FILE_A } });
    fireEvent.change(screen.getByLabelText('Right document'), { target: { value: FILE_B } });
  }

  it('submits only the two selected references and renders lexical results', async () => {
    mocks.post.mockResolvedValue(compared());
    await selectCompare();
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected files' }));
    await waitFor(() => expect(screen.getByRole('status', { name: 'Verified comparison results' })).toBeTruthy());
    expect(mocks.post.mock.calls[0][1]).toEqual({
      operation: 'compare', left_id: FILE_A, right_id: FILE_B,
      references: [{ source_id: FILE_A, revision: SHA }, { source_id: FILE_B, revision: rightSha }],
    });
    expect(screen.getByText('Lexical similarity: 33.33%')).toBeTruthy();
    expect(screen.getByText('warranty')).toBeTruthy();
  });

  it.each([
    { right_sha256: SHA }, { left_id: FILE_B }, { jaccard_similarity: 2 },
    { comparison_semantics: 'semantic' }, { only_left: ['vendor'] },
  ])('rejects invalid comparison evidence %j', async (patch) => {
    mocks.post.mockResolvedValue({ ...compared(), ...patch });
    await selectCompare();
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected files' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.queryByRole('status', { name: 'Verified comparison results' })).toBeNull();
  });

  it('cancels comparison when a source changes', async () => {
    let resolveComparison!: (value: unknown) => void;
    mocks.post.mockImplementation(() => new Promise((resolve) => { resolveComparison = resolve; }));
    await selectCompare();
    fireEvent.click(screen.getByRole('button', { name: 'Compare selected files' }));
    fireEvent.change(screen.getByLabelText('Right document'), { target: { value: '' } });
    await act(async () => resolveComparison(compared()));
    expect(mocks.post.mock.calls[0][2].signal.aborted).toBe(true);
    expect(screen.queryByRole('status', { name: 'Verified comparison results' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Compare selected files' }) as HTMLButtonElement).disabled).toBe(true);
  });
});


describe('Independent Content Intelligence inventory consumer', () => {
  it('uses only the Content Intelligence endpoint and preserves pagination', async () => {
    mocks.get.mockResolvedValueOnce(response(FILE_A, true, 'content-cursor'))
      .mockResolvedValueOnce(response(FILE_B));
    render(<Consumer consumer="content-intelligence" />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Select A'));
    expect(screen.getByRole('button', { name: 'Analyze selected files' })).toBeTruthy();
    fireEvent.click(screen.getByText('Next'));
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('beta.txt'));
    expect(mocks.get.mock.calls).toEqual([
      ['/api/plugins/content-intelligence/inventory?limit=100'],
      ['/api/plugins/content-intelligence/inventory?limit=100&cursor=content-cursor'],
    ]);
    expect(screen.getByTestId('selection').textContent).toBe('');
  });

  it('clears selection and cursor when switching consumers under the same principal', async () => {
    mocks.get.mockResolvedValueOnce(response(FILE_A, true, 'explorer-cursor'))
      .mockResolvedValueOnce(response(FILE_A, true, 'second-cursor'))
      .mockResolvedValueOnce(response(FILE_B));
    const view = render(<Consumer />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('alpha.txt'));
    fireEvent.click(screen.getByText('Next'));
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select A'));
    const oldKey = screen.getByTestId('key').textContent;
    view.rerender(<Consumer consumer="content-intelligence" />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('beta.txt'));
    expect(screen.getByTestId('selection').textContent).toBe('');
    expect(screen.getByTestId('key').textContent).not.toBe(oldKey);
    expect(mocks.get).toHaveBeenLastCalledWith('/api/plugins/content-intelligence/inventory?limit=100');
  });

  it('rejects a late response from the previous consumer', async () => {
    let resolveOld!: (value: unknown) => void;
    mocks.get.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response(FILE_B));
    const view = render(<Consumer />);
    view.rerender(<Consumer consumer="content-intelligence" />);
    await waitFor(() => expect(screen.getByTestId('page').textContent).toBe('beta.txt'));
    await act(async () => resolveOld(response(FILE_A)));
    expect(screen.getByTestId('page').textContent).toBe('beta.txt');
  });

  it('does not fall back to File Explorer after Content Intelligence denial', async () => {
    mocks.get.mockRejectedValue(new Error('denied'));
    render(<Consumer consumer="content-intelligence" />);
    await waitFor(() => expect(screen.getByTestId('error').textContent).toContain('access was denied'));
    expect(screen.getByTestId('authorized').textContent).toBe('false');
    expect(mocks.get.mock.calls).toEqual([['/api/plugins/content-intelligence/inventory?limit=100']]);
  });
});
