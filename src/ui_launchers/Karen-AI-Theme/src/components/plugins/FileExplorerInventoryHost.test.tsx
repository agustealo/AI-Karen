// @vitest-environment jsdom
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SharedFileExplorer, type ExplorerManagement } from '@/plugin_repo/file-explorer/FileExplorerPage';
import { FileExplorerInventoryHost, type InventoryConsumer, type FileExplorerInventoryProps } from './FileExplorerInventoryHost';

import { ContentIntelligenceWorkspace } from './ContentIntelligenceWorkspace';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  useAuth: vi.fn(),
  captureApiPrincipalScope: vi.fn(),
  isCurrentApiPrincipalScope: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  apiClient: { get: mocks.get, post: mocks.post, patch: mocks.patch, delete: mocks.delete },
  captureApiPrincipalScope: mocks.captureApiPrincipalScope,
  isCurrentApiPrincipalScope: mocks.isCurrentApiPrincipalScope,
}));
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
    max_selection: 12,
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

function Consumer({ mode, consumer, onAttach }: { mode?: 'analysis' | 'selection'; consumer?: InventoryConsumer; onAttach?: (refs: { source_id: string; revision: string }[]) => void } = {}) {
  return (
    <FileExplorerInventoryHost hierarchy={false} mode={mode} consumer={consumer} onAttach={onAttach}>
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

type TransportScope = { tenant_id: string; user_id: string; revision: number };
let transportOverride: TransportScope | null | undefined;
const ownerScope: TransportScope = { tenant_id: 'tenant-one', user_id: 'owner-one', revision: 1 };
function transportScope(): TransportScope | null {
  if (transportOverride !== undefined) return transportOverride;
  const state = mocks.useAuth();
  return state?.isAuthenticated && state.user ? {
    tenant_id: state.user.tenant_id, user_id: state.user.user_id, revision: 1,
  } : null;
}

beforeEach(() => {
  transportOverride = undefined;
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.patch.mockReset();
  mocks.delete.mockReset();
  mocks.useAuth.mockReset();
  mocks.useAuth.mockReturnValue(auth());
  mocks.captureApiPrincipalScope.mockReset().mockImplementation((tenant_id: string, user_id: string) => {
    const current = transportScope();
    return current?.tenant_id === tenant_id && current.user_id === user_id ? { ...current } : null;
  });
  mocks.isCurrentApiPrincipalScope.mockReset().mockImplementation((scope: TransportScope) => {
    const current = transportScope();
    return current?.tenant_id === scope.tenant_id && current.user_id === scope.user_id && current.revision === scope.revision;
  });
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

  it('rejects callbacks retained from the previous authorized page', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockResolvedValueOnce(response(FILE_A, true, 'first-cursor'))
      .mockResolvedValueOnce(response(FILE_B, true, 'second-cursor'));
    render(<FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <output>{props.items.map(item => item.name).join(',')}</output>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized && !latest.loading).toBe(true));
    const previous = latest;
    await act(async () => previous.onNextPage('first-cursor'));
    await waitFor(() => expect(latest.authorized && !latest.loading && latest.items[0]?.source_id === FILE_B).toBe(true));
    await act(async () => latest.onSelect([latest.items[0]]));
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    await act(async () => {
      previous.onSelect([]);
      previous.onRefresh();
      previous.onNextPage('first-cursor');
    });
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    expect(latest.items.map(item => item.source_id)).toEqual([FILE_B]);
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.post).not.toHaveBeenCalled();
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
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Search selected files' }));
    });
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

describe('Explicit composer attachment handoff', () => {
  it('passes only verified references after explicit confirmation and rejects forged selections', async () => {
    const onAttach = vi.fn();
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<Consumer mode="selection" onAttach={onAttach} />);
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select A'));
    expect(onAttach).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Attach selected files (1)' }));
    expect(onAttach).toHaveBeenCalledWith([{ source_id: FILE_A, revision: SHA }]);
    fireEvent.click(screen.getByText('Forged hash'));
    expect(screen.queryByRole('button', { name: /Attach selected files/ })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('rejects confirmation from a superseded selection before React commits the next render', async () => {
    let latest!: FileExplorerInventoryProps;
    const onAttach = vi.fn();
    const page = response(FILE_A);
    page.items.push(response(FILE_B).items[0]);
    mocks.get.mockResolvedValue(page);
    render(<FileExplorerInventoryHost hierarchy={false} mode="selection" onAttach={onAttach}>
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => latest.onSelect([latest.items[0]]));
    const prior = screen.getByRole('button', { name: 'Attach selected files (1)' });
    act(() => {
      latest.onSelect([latest.items[1]]);
      prior.click();
    });
    expect(onAttach).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Attach selected files (1)' }));
    expect(onAttach).toHaveBeenCalledTimes(1);
    expect(onAttach).toHaveBeenCalledWith([{ source_id: FILE_B, revision: SHA }]);
  });

  it('revokes the attachment action when authentication is revalidated', async () => {
    const onAttach = vi.fn();
    mocks.get.mockResolvedValue(response(FILE_A));
    const view = render(<Consumer mode="selection" onAttach={onAttach} />);
    await waitFor(() => expect(screen.getByTestId('authorized').textContent).toBe('true'));
    fireEvent.click(screen.getByText('Select A'));
    mocks.useAuth.mockReturnValue({ ...auth(), isLoading: true });
    view.rerender(<Consumer mode="selection" onAttach={onAttach} />);
    expect(screen.queryByRole('button', { name: /Attach selected files/ })).toBeNull();
    expect(onAttach).not.toHaveBeenCalled();
  });
});


describe('Standalone Content Intelligence workspace', () => {
  it('discovers sources independently and mounts the shared investigation operations', async () => {
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<ContentIntelligenceWorkspace />);
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Select alpha.txt' })).toBeTruthy());
    expect(mocks.get.mock.calls).toEqual([['/api/plugins/content-intelligence/inventory?limit=100']]);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select alpha.txt' }));
    expect(screen.getByRole('button', { name: 'Analyze selected files' })).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Search documents' })).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Compare documents' })).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
  });

  it('keeps denied inventory unavailable without falling back or exposing operations', async () => {
    mocks.get.mockRejectedValue(new Error('denied'));
    render(<ContentIntelligenceWorkspace />);
    await waitFor(() => expect(screen.getByText('Document investigation is unavailable until inventory access is verified.')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.get.mock.calls).toEqual([['/api/plugins/content-intelligence/inventory?limit=100']]);
    expect(mocks.post).not.toHaveBeenCalled();
  });
});


describe('governed hierarchy inventory', () => {
  const folderId = '55555555-5555-4555-8555-555555555555';
  function hierarchyPage(parent: string | null = null) {
    return {
      available: true, request_id: 'request', correlation_id: 'correlation',
      folders: parent ? [] : [{ folder_id: folderId, parent_folder_id: null, name: 'Reports', revision: '1' }],
      breadcrumbs: parent ? [{ folder_id: folderId, parent_folder_id: null, name: 'Reports', revision: '1' }] : [],
      has_more: false, next_folder_id: null,
      files: parent ? [{ ...response(FILE_A).items[0], parent_id: parent, organization_revision: '2' }] : [],
      files_has_more: false, next_file_cursor: null,
    };
  }
  function HierarchyConsumer() {
    return <FileExplorerInventoryHost hierarchy mode="selection">
      {props => <div>
        <span data-testid="hierarchy-authorized">{String(props.authorized)}</span>
        <span data-testid="hierarchy-error">{props.error}</span>
        {props.items.map(item => <button key={item.source_id} onClick={() => {
          if (item.kind === 'folder') props.hierarchy?.onNavigate?.(item.source_id);
          else props.onSelect([item]);
        }}>{item.name}</button>)}
        <button onClick={() => props.hierarchy?.onNavigate?.(null)}>Go root</button>
        <span data-testid="hierarchy-selected">{props.selectedSourceIds.join(',')}</span>
      </div>}
    </FileExplorerInventoryHost>;
  }
  it('loads a nested location from the backend and preserves file selection semantics', async () => {
    mocks.get.mockResolvedValueOnce(hierarchyPage()).mockResolvedValueOnce(hierarchyPage(folderId))
      .mockResolvedValueOnce(hierarchyPage());
    render(<HierarchyConsumer />);
    await waitFor(() => expect(screen.getByText('Reports')).toBeTruthy());
    fireEvent.click(screen.getByText('Reports'));
    await waitFor(() => expect(screen.getByText('alpha.txt')).toBeTruthy());
    expect(mocks.get).toHaveBeenNthCalledWith(2,
      '/api/plugins/file-explorer/hierarchy?limit=100&parent_folder_id=' + folderId);
    fireEvent.click(screen.getByText('alpha.txt'));
    expect(screen.getByTestId('hierarchy-selected').textContent).toBe(FILE_A);
    fireEvent.click(screen.getByText('Go root'));
    await waitFor(() => expect(screen.getByText('Reports')).toBeTruthy());
    expect(screen.getByTestId('hierarchy-selected').textContent).toBe('');
  });
  it('rejects a malformed breadcrumb chain instead of displaying foreign location metadata', async () => {
    mocks.get.mockResolvedValueOnce(hierarchyPage()).mockResolvedValueOnce({
      ...hierarchyPage(folderId), breadcrumbs: [],
    });
    render(<HierarchyConsumer />);
    await waitFor(() => expect(screen.getByText('Reports')).toBeTruthy());
    fireEvent.click(screen.getByText('Reports'));
    await waitFor(() => expect(screen.getByTestId('hierarchy-error').textContent).toContain('Invalid file inventory response'));
    expect(screen.getByTestId('hierarchy-authorized').textContent).toBe('false');
    expect(screen.queryByText('alpha.txt')).toBeNull();
  });
});


describe('Explorer management preflight and mutation receipts', () => {
  const folder = '55555555-5555-4555-8555-555555555555';
  const evidence = { request_id: 'request', correlation_id: 'correlation' };
  const inventory = { ...evidence, available: true, breadcrumbs: [],
    folders: [{ folder_id: folder, parent_folder_id: null, name: 'Reports', revision: '7' }],
    has_more: false, next_folder_id: null, files: [], files_has_more: false, next_file_cursor: null };
  function capabilities(deletion = 'available') {
    return { ...evidence, browse: 'available', semantics: 'preflight_not_resource_authorization',
      operations: {
        'file_explorer.folder.create': 'available', 'file_explorer.folder.rename': 'available',
        'file_explorer.folder.move': 'available', 'file_explorer.artifact.move': 'available',
        'file_explorer.folder.delete': deletion,
      } };
  }
  function Manager() {
    return <FileExplorerInventoryHost hierarchy mode="analysis">
      {props => <div>
        <span data-testid="message">{props.management?.message}</span>
        <button disabled={props.management?.capabilities['file_explorer.folder.delete'] !== 'available'}
          onClick={() => props.management?.onMutate({action: 'delete', sourceId: folder, expectedRevision: '7'})}>Delete</button>
        <button onClick={() => props.management?.onMutate({action: 'rename', sourceId: folder, expectedRevision: '6', name: 'Wrong'})}>Stale</button>
        <button disabled={props.management?.capabilities['file_explorer.folder.rename'] !== 'available'}
          onClick={() => props.management?.onMutate({action: 'rename', sourceId: folder, expectedRevision: '7', name: 'New'})}>Rename</button>
      </div>}
    </FileExplorerInventoryHost>;
  }
  it('does not send a denied delete or a stale revision', async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities('denied') : inventory));
    render(<Manager />);
    await waitFor(() => expect((screen.getByText('Rename') as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByText('Delete') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText('Delete'));
    fireEvent.click(screen.getByText('Stale'));
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(mocks.patch).not.toHaveBeenCalled();
  });
  it('uses organization revision, rejects a substituted receipt, refreshes without retrying', async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    mocks.patch.mockResolvedValue({ ...evidence, folder: { folder_id: FILE_A, parent_folder_id: null, name: 'New', revision: '8' } });
    render(<Manager />);
    await waitFor(() => expect((screen.getByText('Rename') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText('Rename'));
    await waitFor(() => expect(screen.getByTestId('message').textContent).toContain('not confirmed'));
    expect(mocks.patch).toHaveBeenCalledWith('/api/plugins/file-explorer/folders/' + folder,
      { name: 'New', expected_revision: '7' }, {}, ownerScope);
    expect(mocks.get.mock.calls.filter(([path]) => path.includes('/hierarchy?'))).toHaveLength(2);
  });
  it('rejects retained mutation and selection callbacks across mode and principal changes', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    function Probe({ mode }: { mode: 'analysis' | 'selection' }) {
      return <FileExplorerInventoryHost hierarchy mode={mode}>
        {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
      </FileExplorerInventoryHost>;
    }
    const view = render(<Probe mode="analysis" />);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.rename']).toBe('available'));
    const old = latest;
    view.rerender(<Probe mode="selection" />);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => {
      old.management?.onMutate({ action: 'rename', sourceId: folder, expectedRevision: '7', name: 'New' });
      old.hierarchy?.onNavigate?.(folder);
      old.onRefresh();
    });
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(mocks.get.mock.calls.filter(([path]) => path.includes('parent_folder_id='))).toHaveLength(0);
    view.rerender(<Probe mode="analysis" />);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.rename']).toBe('available'));
    const other = latest;
    mocks.useAuth.mockReturnValue(auth('owner-two'));
    view.rerender(<Probe mode="analysis" />);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.rename']).toBe('available'));
    await act(async () => other.management?.onMutate({ action: 'rename', sourceId: folder, expectedRevision: '7', name: 'New' }));
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it('binds root creation and its management evidence to the displayed transport principal', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    mocks.post.mockResolvedValue({ ...evidence, folder: { folder_id: FILE_B, parent_folder_id: null, name: 'New', revision: '1' } });
    render(<FileExplorerInventoryHost hierarchy mode="analysis">{props => {
      latest = props; return <span>{String(props.authorized)}</span>;
    }}</FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.create']).toBe('available'));
    expect(mocks.get).toHaveBeenNthCalledWith(1, '/api/plugins/file-explorer/hierarchy?limit=100', ownerScope);
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/api/plugins/file-explorer/capabilities', ownerScope);
    await act(async () => latest.management?.onMutate({ action: 'create', name: 'New' }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledWith('/api/plugins/file-explorer/folders',
      { name: 'New', parent_folder_id: null }, {}, ownerScope);
  });

  it.each([
    { tenant_id: 'tenant-one', user_id: 'owner-two', revision: 2 },
    { tenant_id: 'tenant-two', user_id: 'owner-one', revision: 2 },
    { tenant_id: 'tenant-one', user_id: 'owner-one', revision: 2 },
    null,
  ])('rejects retained organization callbacks before React commits a transport identity transition: %j', async (next) => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    render(<FileExplorerInventoryHost hierarchy mode="analysis">{props => {
      latest = props; return <span>{String(props.authorized)}</span>;
    }}</FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.create']).toBe('available'));
    const retained = latest.management!;
    transportOverride = next;
    await act(async () => {
      await retained.onMutate({ action: 'create', name: 'Previous owner name' });
      await retained.onMutate({ action: 'rename', sourceId: folder, expectedRevision: '7', name: 'New' });
      await retained.onMutate({ action: 'delete', sourceId: folder, expectedRevision: '7' });
      retained.onBrowseDestination?.(folder, '7');
    });
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it('does not request management inventory when UI and transport principals disagree', async () => {
    transportOverride = { tenant_id: 'tenant-one', user_id: 'owner-two', revision: 2 };
    let latest!: FileExplorerInventoryProps;
    render(<FileExplorerInventoryHost hierarchy mode="analysis">{props => {
      latest = props; return <span>{String(props.authorized)}</span>;
    }}</FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.error).toContain('access was denied'));
    expect(latest.authorized).toBe(false);
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('rejects a changed-name receipt that fails to advance the organization revision', async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    mocks.patch.mockResolvedValue({ ...evidence, folder: { folder_id: folder, parent_folder_id: null, name: 'New', revision: '7' } });
    render(<Manager />);
    await waitFor(() => expect((screen.getByText('Rename') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText('Rename'));
    await waitFor(() => expect(screen.getByTestId('message').textContent).toContain('not confirmed'));
    expect(mocks.patch).toHaveBeenCalledTimes(1);
  });

  it('browses nested destinations without replacing the source revision', async () => {
    const child = '66666666-6666-4666-8666-666666666666';
    const source = { ...inventory.folders[0] };
    const destinationFolder = { folder_id: child, parent_folder_id: null, name: 'Archive', revision: '1' };
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockImplementation((path: string) => Promise.resolve(
      path.endsWith('/capabilities') ? capabilities() :
      path.includes('parent_folder_id=' + child) ? { ...inventory, folders: [], breadcrumbs: [destinationFolder] } :
      { ...inventory, folders: [source, destinationFolder] },
    ));
    mocks.post.mockResolvedValue({ ...evidence, kind: 'folder', source_id: folder,
      parent_folder_id: child, organization_revision: '8' });
    render(<FileExplorerInventoryHost hierarchy mode="analysis">
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.move']).toBe('available'));
    await act(async () => latest.management?.onBrowseDestination?.(folder, '7'));
    await waitFor(() => expect(latest.management?.destination?.canConfirm).toBe(true));
    expect(latest.management?.destination?.folders.map(entry => entry.folder_id)).toEqual([child]);
    await act(async () => latest.management?.destination?.onNavigate(child));
    await waitFor(() => expect(latest.management?.destination?.parentId).toBe(child));
    await waitFor(() => expect(latest.management?.destination?.canConfirm).toBe(true));
    expect(latest.items.find(item => item.source_id === folder)?.organization_revision).toBe('7');
    await act(async () => latest.management?.onMutate({ action: 'move', sourceId: folder,
      expectedRevision: '7', destinationId: null }));
    expect(mocks.post).not.toHaveBeenCalled();
    await act(async () => latest.management?.onMutate({ action: 'move', sourceId: folder,
      expectedRevision: '7', destinationId: child }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledWith('/api/plugins/file-explorer/move/folder/' + folder,
      { destination_id: child, expected_revision: '7' }, {}, ownerScope);
  });

  it('does not accept a destination response after cancellation', async () => {
    let latest!: FileExplorerInventoryProps;
    let resolveDestination!: (data: unknown) => void;
    mocks.get.mockResolvedValueOnce(inventory).mockResolvedValueOnce(capabilities())
      .mockImplementationOnce(() => new Promise(resolve => { resolveDestination = resolve; }));
    render(<FileExplorerInventoryHost hierarchy mode="analysis">
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.management?.capabilities['file_explorer.folder.move']).toBe('available'));
    await act(async () => latest.management?.onBrowseDestination?.(folder, '7'));
    const pending = latest.management?.destination;
    expect(pending?.loading).toBe(true);
    await act(async () => pending?.onCancel());
    await act(async () => resolveDestination(inventory));
    expect(latest.management?.destination).toBeUndefined();
    await act(async () => latest.management?.onMutate({ action: 'move', sourceId: folder, expectedRevision: '7', destinationId: null }));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('sends explicit delete revision and confirms only matching evidence', async () => {
    mocks.get.mockImplementation((path: string) => Promise.resolve(path.endsWith('/capabilities') ? capabilities() : inventory));
    mocks.delete.mockResolvedValue({ ...evidence, folder_id: folder, deleted: true });
    render(<Manager />);
    await waitFor(() => expect((screen.getByText('Delete') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText('Delete'));
    await waitFor(() => expect(screen.getByTestId('message').textContent).toContain('confirmed'));
    expect(mocks.delete).toHaveBeenCalledWith('/api/plugins/file-explorer/folders/' + folder,
      { expected_revision: '7' }, {}, ownerScope);
  });
});


describe('shared Explorer accessible organization controls', () => {
  const folder = { source_id: '55555555-5555-4555-8555-555555555555', parent_id: null,
    kind: 'folder' as const, name: 'Reports', revision: '7', organization_revision: '7',
    sha256: null, size_bytes: 0 };
  const hierarchy = { parentId: null, breadcrumbs: [], hasMoreFolders: false, nextFolderId: null };
  function management(onMutate = vi.fn()): ExplorerManagement {
    return { busy: false, message: null, capabilityStatus: 'ready', onMutate,
      capabilities: { 'file_explorer.folder.create': 'available',
        'file_explorer.folder.rename': 'available', 'file_explorer.folder.delete': 'denied' } };
  }
  it('focuses the editor and restores focus on Escape without submitting', () => {
    const controls = management();
    render(<SharedFileExplorer authorized items={[folder]} hierarchy={hierarchy} management={controls} />);
    const rename = screen.getByRole('button', { name: 'Rename Reports' });
    fireEvent.click(rename);
    const input = screen.getByLabelText('Folder name');
    expect(document.activeElement).toBe(input);
    expect((screen.getByRole('button', { name: /^Root$/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByLabelText('Folder name')).toBeNull();
    expect(document.activeElement).toBe(rename);
    expect(controls.onMutate).not.toHaveBeenCalled();
  });
  it('announces denial and rejects an invalid name before submission', () => {
    const controls = management();
    render(<SharedFileExplorer authorized items={[folder]} hierarchy={hierarchy} management={controls} />);
    expect(screen.getByText(/Delete empty folder: permission denied/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Delete Reports' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'New folder' }));
    const input = screen.getByLabelText('Folder name');
    fireEvent.change(input, { target: { value: '   ' } });
    const confirm = screen.getByRole('button', { name: 'Confirm create' });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(screen.getByRole('form', { name: 'Confirm organization change' }));
    expect(controls.onMutate).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Folder name')).toBeTruthy();
  });
  it('moves focus to the authorized content after an explicit page transition', () => {
    const navigate = vi.fn();
    const view = render(<SharedFileExplorer authorized items={[folder]} pageKey="principal:1"
      hierarchy={{...hierarchy, onNavigate: navigate}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open folder Reports' }));
    expect(navigate).toHaveBeenCalledWith(folder.source_id);
    view.rerender(<SharedFileExplorer authorized items={[]} pageKey="principal:2"
      hierarchy={{...hierarchy, parentId: folder.source_id}} />);
    expect(document.activeElement).toBe(screen.getByLabelText('File Explorer content'));
  });
});


describe('governed server filename search', () => {
  it('binds search to pagination and refresh, and clears selection on query changes', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockResolvedValueOnce(response(FILE_A, true, 'old'))
      .mockResolvedValueOnce(response(FILE_B, true, 'bound'))
      .mockResolvedValueOnce(response(FILE_A))
      .mockResolvedValueOnce(response(FILE_B));
    render(<FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <span>{props.items.map(item => item.name).join(',')}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => latest.onSelect([latest.items[0]]));
    const stale = latest;
    await act(async () => latest.onSearch?.(' report_% '));
    await waitFor(() => expect(latest.items[0]?.source_id).toBe(FILE_B));
    expect(latest.search).toBe('report_%');
    expect(latest.selectedSourceIds).toEqual([]);
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/api/plugins/file-explorer/inventory?limit=100&search=report_%25');
    await act(async () => stale.onNextPage('old'));
    expect(mocks.get).toHaveBeenCalledTimes(2);
    await act(async () => latest.onNextPage('bound'));
    await waitFor(() => expect(latest.items[0]?.source_id).toBe(FILE_A));
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/api/plugins/file-explorer/inventory?limit=100&cursor=bound&search=report_%25');
    await act(async () => latest.onRefresh());
    await waitFor(() => expect(latest.items[0]?.source_id).toBe(FILE_B));
    expect(mocks.get).toHaveBeenNthCalledWith(4, '/api/plugins/file-explorer/inventory?limit=100&search=report_%25');
  });
  it('rejects same-principal out-of-order search and stale page callbacks', async () => {
    let latest!: FileExplorerInventoryProps;
    let resolveOld!: (data: ReturnType<typeof response>) => void;
    const delayed = new Promise<ReturnType<typeof response>>(resolve => { resolveOld = resolve; });
    mocks.get.mockResolvedValueOnce(response(FILE_A, true, 'old-cursor'))
      .mockReturnValueOnce(delayed).mockResolvedValueOnce(response(FILE_B, true, 'new-cursor'));
    render(<FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <span>{props.items.map(item => item.name).join(',')}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized && !latest.loading).toBe(true));
    const stale = latest;
    act(() => latest.onSearch?.('old'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    act(() => latest.onSearch?.('new'));
    await waitFor(() => expect(latest.authorized && !latest.loading && latest.search === 'new').toBe(true));
    await act(async () => { resolveOld(response(FILE_A)); await delayed; });
    act(() => latest.onSelect([latest.items[0]]));
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    act(() => { stale.onSelect([]); stale.onRefresh(); stale.onNextPage('old-cursor'); });
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    expect(latest.items.map(item => item.source_id)).toEqual([FILE_B]);
    expect(mocks.get).toHaveBeenCalledTimes(3);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('clears Content Intelligence filename search through its own authorized endpoint', async () => {
    mocks.get.mockResolvedValueOnce(response(FILE_A))
      .mockResolvedValueOnce(response(FILE_B)).mockResolvedValueOnce(response(FILE_A));
    render(<ContentIntelligenceWorkspace />);
    await screen.findByRole('checkbox', { name: 'Select alpha.txt' });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search authorized filenames' }), { target: { value: 'report_%' } });
    fireEvent.submit(screen.getByRole('form', { name: 'Search authorized filenames' }));
    await screen.findByRole('checkbox', { name: 'Select beta.txt' });
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/api/plugins/content-intelligence/inventory?limit=100&search=report_%25');
    fireEvent.click(screen.getByRole('button', { name: /^Clear search$/ }));
    await screen.findByRole('checkbox', { name: 'Select alpha.txt' });
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/api/plugins/content-intelligence/inventory?limit=100');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('discards a delayed query result and resets query on principal changes', async () => {
    let latest!: FileExplorerInventoryProps;
    let finish!: (data: unknown) => void;
    mocks.get.mockResolvedValueOnce(response(FILE_A))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response(FILE_B));
    function Probe() { return <FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <span>{props.items.map(item => item.name).join(',')}</span>; }}
    </FileExplorerInventoryHost>; }
    const view = render(<Probe />);
    await waitFor(() => expect(latest.authorized).toBe(true));
    const stale = latest;
    await act(async () => latest.onSearch?.('private'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    mocks.useAuth.mockReturnValue(auth('owner-two'));
    view.rerender(<Probe />);
    await waitFor(() => expect(latest.items[0]?.source_id).toBe(FILE_B));
    await act(async () => finish(response(FILE_A)));
    await act(async () => stale.onSearch?.('private'));
    expect(latest.search).toBe('');
    expect(latest.items[0]?.source_id).toBe(FILE_B);
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/api/plugins/file-explorer/inventory?limit=100');
    expect(mocks.get).toHaveBeenCalledTimes(3);
  });
  it('rejects invalid queries without changing the current page or selection', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockResolvedValue(response(FILE_A));
    render(<FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => latest.onSelect([latest.items[0]]));
    await act(async () => {
      for (const value of ['x'.repeat(161), 'bad\nquery', 'bad\u0000query', '\uD800']) latest.onSearch?.(value);
    });
    expect(latest.selectedSourceIds).toEqual([FILE_A]);
    expect(latest.search).toBe('');
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
  it('does not revive a query after logout and return to the same principal', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockResolvedValue(response(FILE_A));
    function Probe() { return <FileExplorerInventoryHost hierarchy={false} mode="selection">
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>; }
    const view = render(<Probe />);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => latest.onSearch?.('private'));
    await waitFor(() => expect(latest.authorized && latest.search === 'private').toBe(true));
    const stale = latest;
    mocks.useAuth.mockReturnValue({ ...auth(), isAuthenticated: false, user: null });
    view.rerender(<Probe />);
    expect(latest.authorized).toBe(false);
    mocks.useAuth.mockReturnValue(auth());
    view.rerender(<Probe />);
    await waitFor(() => expect(latest.authorized).toBe(true));
    await act(async () => stale.onSearch?.('private'));
    expect(latest.search).toBe('');
    expect(mocks.get).toHaveBeenLastCalledWith('/api/plugins/file-explorer/inventory?limit=100');
    expect(mocks.get).toHaveBeenCalledTimes(3);
  });
  it('submits explicit search without replacing the local page filter', () => {
    const onSearch = vi.fn();
    const item = { ...response(FILE_A).items[0], kind: 'file' as const };
    render(<SharedFileExplorer authorized items={[item]} onSearch={onSearch} />);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter current folder' }), { target: { value: 'alpha' } });
    expect(onSearch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search authorized filenames' }), { target: { value: 'report' } });
    fireEvent.submit(screen.getByRole('form', { name: 'Search authorized filenames' }));
    expect(onSearch).toHaveBeenCalledWith('report');
  });
});


describe('consumer-specific reference capacity', () => {
  const draft = Array.from({length: 11}, (_, index) => ({
    source_id: '77777777-7777-4777-8777-' + String(index).padStart(12, '0'), revision: SHA,
  }));
  it('enforces the backend analysis ceiling rather than the generic UI limit', async () => {
    let latest!: FileExplorerInventoryProps;
    const page = response(FILE_A);
    page.items.push(response(FILE_B).items[0]);
    mocks.get.mockResolvedValue({ ...page, max_selection: 1 });
    render(<FileExplorerInventoryHost consumer="content-intelligence" mode="analysis">
      {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
    </FileExplorerInventoryHost>);
    await waitFor(() => expect(latest.authorized).toBe(true));
    expect(latest.maxSelection).toBe(1);
    await act(async () => latest.onSelect([latest.items[0]]));
    expect(latest.selectedSourceIds).toEqual([FILE_A]);
    await act(async () => latest.onSelect(latest.items));
    expect(latest.selectedSourceIds).toEqual([]);
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it.each([undefined, null, true, '12', 0, -1, 1.5, 201])('fails closed on invalid Content Intelligence selection evidence %s', async (max_selection) => {
    mocks.get.mockResolvedValue({ ...response(FILE_A), max_selection });
    render(<Consumer consumer="content-intelligence" />);
    await waitFor(() => expect(screen.getByTestId('error').textContent).toContain('Invalid file inventory response'));
    expect(screen.getByTestId('authorized').textContent).toBe('false');
  });
  it('enforces the thirteenth selection boundary through the investigation workspace', async () => {
    const page = response(FILE_A);
    page.items = Array.from({ length: 13 }, (_, i) => ({
      ...page.items[0],
      source_id: '44444444-4444-4444-8444-' + String(i + 1).padStart(12, '0'),
      name: 'file-' + String(i + 1).padStart(2, '0') + '.txt',
    }));
    mocks.get.mockResolvedValue(page);
    render(<ContentIntelligenceWorkspace />);
    await screen.findByRole('checkbox', { name: 'Select file-01.txt' });
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes).toHaveLength(13);
    boxes.slice(0, 12).forEach(box => fireEvent.click(box));
    expect(boxes[12].disabled).toBe(true);
    expect(screen.getByText(/Selection limit reached/)).toBeTruthy();
    fireEvent.click(boxes[0]);
    expect(boxes[12].disabled).toBe(false);
    fireEvent.click(boxes[12]);
    expect(boxes[12].checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(boxes.every(box => !box.checked && !box.disabled)).toBe(true);
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('excludes attached references, enforces remaining capacity and revokes stale callbacks', async () => {
    let latest!: FileExplorerInventoryProps;
    const onAttach = vi.fn();
    const page = response(FILE_A);
    page.items.push(response(FILE_B).items[0]);
    mocks.get.mockResolvedValue(page);
    function Probe({ existing }: { existing: typeof draft }) {
      return <FileExplorerInventoryHost hierarchy={false} mode="selection" existingAttachments={existing} onAttach={onAttach}>
        {props => { latest = props; return <span>{String(props.authorized)}</span>; }}
      </FileExplorerInventoryHost>;
    }
    const view = render(<Probe existing={draft} />);
    await waitFor(() => expect(latest.maxSelection).toBe(1));
    const stale = latest;
    await act(async () => latest.onSelect(latest.items));
    expect(latest.selectedSourceIds).toEqual([]);
    await act(async () => latest.onSelect([latest.items[0]]));
    expect(latest.selectedSourceIds).toEqual([FILE_A]);
    view.rerender(<Probe existing={[...draft, {source_id: FILE_A, revision: SHA}]} />);
    expect(latest.maxSelection).toBe(0);
    expect(latest.items.map(item => item.source_id)).toEqual([FILE_B]);
    expect(latest.selectedSourceIds).toEqual([]);
    view.rerender(<Probe existing={draft} />);
    await act(async () => stale.onSelect([stale.items[0]]));
    expect(latest.selectedSourceIds).toEqual([]);
    expect(onAttach).not.toHaveBeenCalled();
  });
});


describe('hierarchy-aware visual controls', () => {
  const folder = { source_id: '55555555-5555-4555-8555-555555555555', parent_id: null,
    kind: 'folder' as const, name: 'Reports', revision: '1', organization_revision: '1', sha256: null, size_bytes: 0 };
  const hierarchy = { parentId: null, breadcrumbs: [], hasMoreFolders: false, nextFolderId: null };
  const first = { ...response(FILE_A).items[0], kind: 'file' as const, size_bytes: 100 };
  const second = { ...response(FILE_B).items[0], kind: 'file' as const, size_bytes: 5 };
  it('preserves selection and local filter across layouts and keeps folders first when sorting', () => {
    const onSelect = vi.fn();
    render(<SharedFileExplorer authorized items={[folder, first, second]} hierarchy={hierarchy}
      maxSelection={2} onSelect={onSelect} />);
    fireEvent.change(screen.getByLabelText('Sort current page'), { target: { value: 'size-asc' } });
    const list = screen.getByRole('list', { name: 'Files and folders' });
    expect(Array.from(list.children).map(node => node.textContent)).toEqual([
      expect.stringContaining('Reports'), expect.stringContaining('beta.txt'), expect.stringContaining('alpha.txt'),
    ]);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select alpha.txt' }));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter current folder' }), { target: { value: 'beta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Grid view' }));
    expect(screen.getByRole('button', { name: 'Grid view' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText(/1 selected · 1 shown/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Review selection (1)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove alpha.txt from selection' }));
    expect(onSelect).toHaveBeenLastCalledWith([]);
  });
  it('bulk selection excludes folders and refuses overflow without truncating', () => {
    const onSelect = vi.fn();
    render(<SharedFileExplorer authorized items={[folder, first, second]} hierarchy={hierarchy}
      maxSelection={1} onSelect={onSelect} />);
    expect(screen.queryByRole('checkbox', { name: 'Select Reports' })).toBeNull();
    const bulk = screen.getByRole('button', { name: 'Select visible files (2)' });
    expect((bulk as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Selection would exceed the limit/)).toBeTruthy();
    fireEvent.click(bulk);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter current folder' }), { target: { value: 'alpha' } });
    fireEvent.click(screen.getByRole('button', { name: 'Select visible files (1)' }));
    expect(onSelect).toHaveBeenLastCalledWith([{ source_id: FILE_A, revision: SHA, sha256: SHA, kind: 'file' }]);
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }));
    expect(onSelect).toHaveBeenLastCalledWith([]);
  });
  it('reports a genuinely empty authorized inventory through the investigation workspace', async () => {
    mocks.get.mockResolvedValue({ ...response(FILE_A), items: [] });
    render(<ContentIntelligenceWorkspace />);
    await screen.findByText('No files or folders in this view.');
    expect(screen.queryByText('No matching references on this page.')).toBeNull();
    expect(screen.queryByText('No matching files or folders on this search page.')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Analyze selected files' })).toBeNull();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('keeps layout and hidden selection changes local to the investigation workspace', async () => {
    const page = response(FILE_A);
    page.items = [
      { ...page.items[0], size_bytes: 20 },
      { ...response(FILE_B).items[0], size_bytes: 10 },
    ];
    mocks.get.mockResolvedValue(page);
    render(<ContentIntelligenceWorkspace />);
    await screen.findByRole('checkbox', { name: 'Select alpha.txt' });
    fireEvent.change(screen.getByLabelText('Sort current page'), { target: { value: 'size-asc' } });
    expect(screen.getAllByRole('checkbox').map(box => box.getAttribute('aria-label'))).toEqual([
      'Select beta.txt', 'Select alpha.txt',
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Select visible files (2)' }));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter current folder' }), { target: { value: 'alpha' } });
    for (const layout of ['Grid view', 'List view']) {
      fireEvent.click(screen.getByRole('button', { name: layout }));
      expect(screen.getByRole('button', { name: layout }).getAttribute('aria-pressed')).toBe('true');
      const otherLayout = layout === 'Grid view' ? 'List view' : 'Grid view';
      expect(screen.getByRole('button', { name: otherLayout }).getAttribute('aria-pressed')).toBe('false');
      expect(screen.getByRole('list', { name: 'Files and folders' }).className).toContain(layout === 'Grid view' ? 'grid' : 'flex-col');
      expect((screen.getByRole('searchbox', { name: 'Filter current folder' }) as HTMLInputElement).value).toBe('alpha');
      expect((screen.getByRole('checkbox', { name: 'Select alpha.txt' }) as HTMLInputElement).checked).toBe(true);
      expect(screen.queryByRole('checkbox', { name: 'Select beta.txt' })).toBeNull();
      expect(screen.getByRole('button', { name: 'Review selection (2)' })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole('button', { name: 'Review selection (2)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove beta.txt from selection' }));
    expect(screen.getByRole('button', { name: 'Review selection (1)' })).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: 'Select alpha.txt' }) as HTMLInputElement).checked).toBe(true);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.patch).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
  });

  it('distinguishes a filtered page from genuinely empty inventory', () => {
    const onNextPage = vi.fn();
    render(<SharedFileExplorer authorized items={[first]} hasMore
      nextCursor="owner-scoped-cursor" onNextPage={onNextPage} />);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter current folder' }), { target: { value: 'missing' } });
    expect(screen.getByText('No matching references on this page.')).toBeTruthy();
    expect(screen.getByText(/Filtering and sorting apply only to this page/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filter' }));
    expect(screen.getByRole('checkbox', { name: 'Select alpha.txt' })).toBeTruthy();
    expect(onNextPage).not.toHaveBeenCalled();
  });
});

describe('KEXP-003F capacity transition isolation', () => {
  it('clears pending selections on a full draft and rejects ABA callback replay after capacity returns', async () => {
    let latest!: FileExplorerInventoryProps;
    const page = response(FILE_A);
    page.items.push(response(FILE_B).items[0]);
    mocks.get.mockResolvedValue(page);
    const onAttach = vi.fn();
    const existing = Array.from({ length: 12 }, (_, i) => ({
      source_id: '66666666-6666-4666-8666-' + String(i + 1).padStart(12, '0'),
      revision: SHA,
    }));
    const view = (count: number) => <FileExplorerInventoryHost hierarchy={false} mode="selection"
      existingAttachments={existing.slice(0, count)} onAttach={onAttach}>{props => {
      latest = props;
      return <output>{props.items.map(item => item.name).join(',')}</output>;
    }}</FileExplorerInventoryHost>;
    const rendered = render(view(10));
    await waitFor(() => expect(latest.authorized && !latest.loading).toBe(true));
    const refs = [FILE_A, FILE_B].map(source_id => ({
      source_id, revision: SHA, sha256: SHA, kind: 'file' as const,
    }));
    act(() => latest.onSelect(refs));
    expect(latest.selectedSourceIds).toEqual([FILE_A, FILE_B]);
    const stale = latest;
    rendered.rerender(view(12));
    expect(latest.maxSelection).toBe(0);
    expect(latest.selectedSourceIds).toEqual([]);
    expect(screen.queryByRole('button', { name: /Attach selected files/ })).toBeNull();
    act(() => latest.onSelect(refs.slice(0, 1)));
    expect(latest.selectedSourceIds).toEqual([]);
    rendered.rerender(view(10));
    expect(latest.maxSelection).toBe(2);
    expect(latest.selectedSourceIds).toEqual([]);
    act(() => latest.onSelect(refs.slice(1)));
    act(() => { stale.onSelect(refs); stale.onRefresh(); stale.onSearch?.('stale'); });
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(onAttach).not.toHaveBeenCalled();
  });

  it('invalidates selection when an attached source revision changes without changing capacity', async () => {
    let latest!: FileExplorerInventoryProps;
    mocks.get.mockResolvedValue(response(FILE_B));
    const view = (revision: string) => <FileExplorerInventoryHost hierarchy={false} mode="selection"
      existingAttachments={[{ source_id: FILE_A, revision }]}>{props => {
      latest = props;
      return <output>{props.items.map(item => item.name).join(',')}</output>;
    }}</FileExplorerInventoryHost>;
    const rendered = render(view(SHA));
    await waitFor(() => expect(latest.authorized && !latest.loading).toBe(true));
    const ref = { source_id: FILE_B, revision: SHA, sha256: SHA, kind: 'file' as const };
    act(() => latest.onSelect([ref]));
    const stale = latest;
    expect(latest.selectedSourceIds).toEqual([FILE_B]);
    rendered.rerender(view('b'.repeat(64)));
    expect(latest.maxSelection).toBe(11);
    expect(latest.selectedSourceIds).toEqual([]);
    act(() => stale.onSelect([ref]));
    expect(latest.selectedSourceIds).toEqual([]);
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
});
