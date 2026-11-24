'use client';

/**
 * Authenticated host for the single dynamically loaded File Explorer UI.
 *
 * Only the canonical API authorizes inventory reads. This component receives
 * no storage credentials and cannot grant read access to selected references.
 * Requests made by an earlier principal or page generation never update state.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { ContentIntelligenceSelectionPanel } from './ContentIntelligenceSelectionPanel';

interface ExplorerItem {
  source_id: string;
  parent_id: null;
  kind: 'file';
  name: string;
  revision: string;
  size_bytes: number;
  sha256: string;
}

interface ExplorerSelection {
  source_id: string;
  revision: string;
  sha256: string | null;
  kind: 'file' | 'folder';
}

interface InventoryPage {
  items: ExplorerItem[];
  has_more: boolean;
  next_cursor: string | null;
  inventory_semantics: 'owner_metadata_page_not_live_acl';
  request_id: string;
  correlation_id: string;
}

interface ScopedPage extends InventoryPage {
  principalKey: string;
  generation: number;
}

interface PageRequest {
  principalKey: string;
  cursor: string | null;
  generation: number;
}

export interface FileExplorerInventoryProps extends Record<string, unknown> {
  authorized: boolean;
  items: ExplorerItem[];
  loading: boolean;
  error: string | null;
  selectedSourceIds: string[];
  onSelect: (references: ExplorerSelection[]) => void;
  onRefresh: () => void;
  hasMore: boolean;
  nextCursor: string | null;
  onNextPage: (cursor: string) => void;
  pageKey: string;
}

const HEX_SHA256 = /^[a-f0-9]{64}$/;
const MAX_PAGE_SIZE = 200;
const MAX_CURSOR_LENGTH = 768;

function assertInventoryPage(data: unknown): InventoryPage {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid file inventory response');
  }
  const page = data as Record<string, unknown>;
  if (
    !Array.isArray(page.items) ||
    page.items.length > MAX_PAGE_SIZE ||
    typeof page.has_more !== 'boolean' ||
    page.inventory_semantics !== 'owner_metadata_page_not_live_acl' ||
    typeof page.request_id !== 'string' ||
    !page.request_id ||
    typeof page.correlation_id !== 'string' ||
    !page.correlation_id ||
    (
      page.has_more
        ? typeof page.next_cursor !== 'string' ||
          page.next_cursor.length < 1 ||
          page.next_cursor.length > MAX_CURSOR_LENGTH ||
          page.items.length === 0
        : page.next_cursor !== null
    )
  ) {
    throw new Error('Invalid file inventory response');
  }

  const seen = new Set<string>();
  const items: ExplorerItem[] = [];
  for (const raw of page.items) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      throw new Error('Invalid file inventory entry');
    }
    const item = raw as Record<string, unknown>;
    if (
      typeof item.source_id !== 'string' ||
      !/^[a-f0-9-]{36}$/.test(item.source_id) ||
      seen.has(item.source_id) ||
      item.parent_id !== null ||
      item.kind !== 'file' ||
      typeof item.name !== 'string' ||
      !item.name ||
      item.name.length > 256 ||
      typeof item.revision !== 'string' ||
      !HEX_SHA256.test(item.revision) ||
      typeof item.sha256 !== 'string' ||
      !HEX_SHA256.test(item.sha256) ||
      item.revision !== item.sha256 ||
      typeof item.size_bytes !== 'number' ||
      !Number.isSafeInteger(item.size_bytes) ||
      item.size_bytes < 0
    ) {
      throw new Error('Invalid file inventory entry');
    }
    seen.add(item.source_id);
    items.push({
      source_id: item.source_id,
      parent_id: null,
      kind: 'file',
      name: item.name,
      revision: item.revision,
      size_bytes: item.size_bytes,
      sha256: item.sha256,
    });
  }
  return {
    items,
    has_more: page.has_more as boolean,
    next_cursor: page.next_cursor as string | null,
    inventory_semantics: 'owner_metadata_page_not_live_acl',
    request_id: page.request_id as string,
    correlation_id: page.correlation_id as string,
  };
}

export function FileExplorerInventoryHost({
  children,
  mode = 'analysis',
  onAttach,
}: {
  children: (props: FileExplorerInventoryProps) => ReactNode;
  /** Selection mode exposes metadata only; it never mounts the analysis workflow. */
  mode?: 'analysis' | 'selection';
  onAttach?: (references: { source_id: string; revision: string }[]) => void;
}) {
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const principalKey = useMemo(() => {
    if (!isAuthenticated || !user?.user_id || !user?.tenant_id) {
      return '';
    }
    return [
      user.tenant_id,
      user.user_id,
      [...(user.roles || [])].sort().join(','),
      [...(user.permissions || [])].sort().join(','),
    ].join('|');
  }, [isAuthenticated, user]);

  const [request, setRequest] = useState<PageRequest>({
    principalKey: '',
    cursor: null,
    generation: 0,
  });
  const [page, setPage] = useState<ScopedPage | null>(null);
  const [errorState, setErrorState] = useState<{ principalKey: string; message: string } | null>(null);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const generationRef = useRef(0);

  useEffect(() => {
    // The source is authenticated API truth, never browser-supplied inventory.
    if (!principalKey || authLoading) {
      generationRef.current += 1;
      setPage(null);
      setSelectedSourceIds([]);
      setErrorState(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const generation = ++generationRef.current;
    const cursor = request.principalKey === principalKey ? request.cursor : null;

    setLoading(true);
    setPage(null);
    setErrorState(null);
    setSelectedSourceIds([]);

    const endpoint = '/api/plugins/file-explorer/inventory?limit=100' +
      (cursor ? '&cursor=' + encodeURIComponent(cursor) : '');

    void apiClient.get<unknown>(endpoint)
      .then((data) => {
        if (cancelled || generationRef.current !== generation) return;
        const verified = assertInventoryPage(data);
        setPage({ ...verified, principalKey, generation });
      })
      .catch((error: unknown) => {
        if (cancelled || generationRef.current !== generation) return;
        // Failure is not an empty authorized inventory. Avoid exposing API
        // error payloads containing tenancy or internal runtime detail.
        setPage(null);
        setErrorState({
          principalKey,
          message: error instanceof Error && error.message === 'Invalid file inventory response'
            ? 'Invalid file inventory response.'
            : 'File inventory is unavailable or access was denied.',
        });
      })
      .finally(() => {
        if (!cancelled && generationRef.current === generation) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      generationRef.current += 1;
    };
  }, [principalKey, authLoading, request]);

  const currentPage = !authLoading && principalKey && page?.principalKey === principalKey ? page : null;
  const currentError = !authLoading && principalKey && errorState?.principalKey === principalKey ? errorState.message : null;

  const onSelect = useCallback((references: ExplorerSelection[]) => {
    if (!currentPage || loading || currentError) {
      setSelectedSourceIds([]);
      return;
    }
    // A plugin UI event is untrusted presentation input, not authority.
    // Never accept a remembered ID with a forged/stale revision or hash.
    // Reject the entire event rather than partially accepting mixed evidence.
    if (!Array.isArray(references) || references.length > 24) {
      setSelectedSourceIds([]);
      return;
    }
    const byId = new Map(currentPage.items.map((item) => [item.source_id, item]));
    const seen = new Set<string>();
    const accepted: string[] = [];
    for (const reference of references) {
      const item = reference && typeof reference.source_id === 'string'
        ? byId.get(reference.source_id) : undefined;
      if (
        !item ||
        seen.has(item.source_id) ||
        reference.kind !== item.kind ||
        reference.revision !== item.revision ||
        reference.sha256 !== item.sha256
      ) {
        setSelectedSourceIds([]);
        return;
      }
      seen.add(item.source_id);
      accepted.push(item.source_id);
    }
    setSelectedSourceIds(accepted);
  }, [currentPage, loading, currentError]);

  const onRefresh = useCallback(() => {
    if (!principalKey) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      principalKey,
      cursor: null,
      generation: value.generation + 1,
    }));
  }, [principalKey]);

  const onNextPage = useCallback((cursor: string) => {
    if (
      !principalKey || !currentPage || loading || currentError ||
      !currentPage.has_more || currentPage.next_cursor !== cursor
    ) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      principalKey,
      cursor,
      generation: value.generation + 1,
    }));
  }, [principalKey, currentPage, loading, currentError]);

  const props: FileExplorerInventoryProps = {
    authorized: Boolean(currentPage && !currentError),
    items: currentPage?.items || [],
    loading: Boolean(principalKey && !authLoading && (loading || (!currentPage && !currentError))),
    error: currentError,
    selectedSourceIds: currentPage && !currentError ? selectedSourceIds : [],
    onSelect,
    onRefresh,
    hasMore: currentPage?.has_more || false,
    nextCursor: currentPage?.next_cursor || null,
    onNextPage,
    pageKey: principalKey + ':' + (currentPage?.generation ?? 'pending'),
  };

  const selectedAnalysisSources = mode === 'analysis' && currentPage && !currentError && !loading
    ? selectedSourceIds.flatMap((id) => {
      const item = currentPage.items.find((entry) => entry.source_id === id);
      return item ? [{ source_id: item.source_id, revision: item.revision }] : [];
    })
    : [];
  const selectedDraftSources = mode === 'selection' && currentPage && !currentError && !loading
    ? selectedSourceIds.flatMap(id => {
      const item = currentPage.items.find(entry => entry.source_id === id);
      return item ? [{ source_id: item.source_id, revision: item.revision }] : [];
    })
    : [];
  const selectionKey = props.pageKey + ':' +
    selectedAnalysisSources.map((source) => source.source_id + ':' + source.revision).join('|');

  return (
    <>
      {children(props)}
      {mode === 'selection' && onAttach && selectedDraftSources.length > 0 && (
        <button type="button" className="m-2 min-h-11 rounded-lg border border-input px-3 text-sm"
          onClick={() => {
            if (!currentPage || currentPage.generation !== generationRef.current) return;
            onAttach(selectedDraftSources);
          }}>
          Attach selected files ({selectedDraftSources.length})
        </button>
      )}
      {selectedAnalysisSources.length > 0 && (
        <ContentIntelligenceSelectionPanel
          key={selectionKey}
          sources={selectedAnalysisSources}
          onRefreshInventory={onRefresh}
        />
      )}
    </>
  );
}
