'use client';

/**
 * Authenticated owner inventory host shared by governed document consumers.
 *
 * Only the canonical API authorizes inventory reads. This component receives
 * no storage credentials and cannot grant read access to selected references.
 * Requests made by an earlier principal or page generation never update state.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { MAX_DRAFT_ATTACHMENTS, type DraftAttachment } from '../chat/copilotkit/useKarenPersistedDraft';
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
  maxSelection: number;
  has_more: boolean;
  next_cursor: string | null;
  inventory_semantics: 'owner_metadata_page_not_live_acl';
  request_id: string;
  correlation_id: string;
}

interface ScopedPage extends InventoryPage {
  scopeIdentity: object;
  principalKey: string;
  generation: number;
}

interface PageRequest {
  scopeIdentity?: object;
  principalKey: string;
  cursor: string | null;
  search: string;
  generation: number;
}

export interface FileExplorerInventoryProps extends Record<string, unknown> {
  authorized: boolean;
  maxSelection: number;
  items: ExplorerItem[];
  loading: boolean;
  error: string | null;
  selectedSourceIds: string[];
  onSelect: (references: ExplorerSelection[]) => void;
  onRefresh: () => void;
  search: string;
  onSearch?: (search: string) => void;
  hasMore: boolean;
  nextCursor: string | null;
  onNextPage: (cursor: string) => void;
  pageKey: string;
}

export type InventoryConsumer = 'file-explorer' | 'content-intelligence';

const INVENTORY_ENDPOINTS: Record<InventoryConsumer, string> = {
  'file-explorer': '/api/plugins/file-explorer/inventory',
  'content-intelligence': '/api/plugins/content-intelligence/inventory',
};

const HEX_SHA256 = /^[a-f0-9]{64}$/;
const MAX_PAGE_SIZE = 200;
const MAX_CURSOR_LENGTH = 768;

// Legacy generic inventory has no execution capability metadata. Preserve its
// draft-only cap; analysis remains bounded by the existing legacy panel contract.
const LEGACY_DRAFT_LIMIT = MAX_DRAFT_ATTACHMENTS;
const LEGACY_ANALYSIS_LIMIT = 12;

function assertInventoryPage(data: unknown, consumer: InventoryConsumer, mode: 'analysis' | 'selection'): InventoryPage {
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

  const maxSelection = consumer === 'content-intelligence' ? page.max_selection
    : mode === 'analysis' ? LEGACY_ANALYSIS_LIMIT : LEGACY_DRAFT_LIMIT;
  if (typeof maxSelection !== 'number' || !Number.isSafeInteger(maxSelection) || maxSelection < 1 || maxSelection > MAX_PAGE_SIZE) {
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
    maxSelection,
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
  consumer = 'file-explorer',
  onAttach,
  existingAttachments = [],
  renderAnalysis,
}: {
  children: (props: FileExplorerInventoryProps) => ReactNode;
  /** Selection mode exposes metadata only; it never mounts the analysis workflow. */
  mode?: 'analysis' | 'selection';
  /** Trusted UI composition selects a fixed endpoint; the server authorizes it. */
  consumer?: InventoryConsumer;
  existingAttachments?: readonly DraftAttachment[];
  onAttach?: (references: { source_id: string; revision: string }[]) => void;
  /** Optional layout slot; authorization and selection remain host-owned. */
  renderAnalysis?: (panel: ReactNode, props: FileExplorerInventoryProps) => ReactNode;
}) {
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const principalKey = useMemo(() => {
    if (!isAuthenticated || !user?.user_id || !user?.tenant_id) {
      return '';
    }
    return [
      consumer,
      mode,
      user.tenant_id,
      user.user_id,
      [...(user.roles || [])].sort().join(','),
      [...(user.permissions || [])].sort().join(','),
    ].join('|');
  }, [isAuthenticated, user, consumer, mode]);

  // Each committed authentication scope has a distinct identity, even on A → B → A.
  const scopeIdentity = useMemo(() => ({ principalKey, authLoading }), [principalKey, authLoading]);
  const [request, setRequest] = useState<PageRequest>({
    principalKey: '',
    cursor: null,
    search: '',
    generation: 0,
  });
  const [page, setPage] = useState<ScopedPage | null>(null);
  const [errorState, setErrorState] = useState<{ scopeIdentity: object; principalKey: string; message: string } | null>(null);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const generationRef = useRef(0);
  const scopeRef = useRef(scopeIdentity);
  useLayoutEffect(() => {
    scopeRef.current = scopeIdentity;
    return () => { scopeRef.current = { principalKey: '', authLoading: true }; };
  }, [scopeIdentity]);

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
    const cursor = request.scopeIdentity === scopeIdentity ? request.cursor : null;
    const search = request.scopeIdentity === scopeIdentity ? request.search : '';

    setLoading(true);
    setPage(null);
    setErrorState(null);
    setSelectedSourceIds([]);

    const endpoint = INVENTORY_ENDPOINTS[consumer] + '?limit=100' +
      (cursor ? '&cursor=' + encodeURIComponent(cursor) : '') +
      (search ? '&search=' + encodeURIComponent(search) : '');

    void apiClient.get<unknown>(endpoint)
      .then((data) => {
        if (cancelled || generationRef.current !== generation) return;
        const verified = assertInventoryPage(data, consumer, mode);
        setPage({ ...verified, principalKey, scopeIdentity, generation });
      })
      .catch((error: unknown) => {
        if (cancelled || generationRef.current !== generation) return;
        // Failure is not an empty authorized inventory. Avoid exposing API
        // error payloads containing tenancy or internal runtime detail.
        setPage(null);
        setErrorState({
          scopeIdentity,
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
  }, [principalKey, authLoading, request, consumer, mode, scopeIdentity]);

  const currentPage = !authLoading && principalKey && page?.scopeIdentity === scopeIdentity ? page : null;
  const currentError = !authLoading && principalKey && errorState?.scopeIdentity === scopeIdentity ? errorState.message : null;

  const attachedIds = new Set(existingAttachments.map(item => item.source_id));
  const capacity = currentPage ? Math.max(0, Math.min(currentPage.maxSelection,
    mode === 'selection' ? MAX_DRAFT_ATTACHMENTS - attachedIds.size : currentPage.maxSelection)) : 0;
  const selectableItems = currentPage?.items.filter(item => mode !== 'selection' || !attachedIds.has(item.source_id)) ?? [];
  const selectableIds = new Set(selectableItems.map(item => item.source_id));
  const effectiveSelection = selectedSourceIds.filter(id => selectableIds.has(id));
  const capacityKey = JSON.stringify([capacity, ...existingAttachments
    .map(item => JSON.stringify([item.source_id, item.revision])).sort()]);
  // A new identity on every capacity transition prevents A → B → A replay.
  // Comparing only a serialized value would revive callbacks from state A.
  const capacityIdentity = useMemo(() => ({ key: capacityKey }), [capacityKey]);
  const capacityRef = useRef(capacityIdentity);
  const capacityChanged = capacityRef.current !== capacityIdentity;
  useLayoutEffect(() => {
    if (capacityRef.current !== capacityIdentity) {
      capacityRef.current = capacityIdentity;
      setSelectedSourceIds([]);
    }
  }, [capacityIdentity]);
  const callbackGeneration = generationRef.current;
  const isCurrentCallback = useCallback(() => !scopeRef.current.authLoading &&
    scopeRef.current === scopeIdentity &&
    generationRef.current === callbackGeneration && capacityRef.current === capacityIdentity,
  [scopeIdentity, callbackGeneration, capacityIdentity]);

  const onSelect = useCallback((references: ExplorerSelection[]) => {
    if (!isCurrentCallback()) return;
    if (!currentPage || currentPage.generation !== generationRef.current || loading || currentError) {
      setSelectedSourceIds([]);
      return;
    }
    // A plugin UI event is untrusted presentation input, not authority.
    // Never accept a remembered ID with a forged/stale revision or hash.
    // Reject the entire event rather than partially accepting mixed evidence.
    if (!Array.isArray(references) || references.length > capacity) {
      setSelectedSourceIds([]);
      return;
    }
    const byId = new Map(selectableItems.map((item) => [item.source_id, item]));
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
  }, [currentPage, loading, currentError, isCurrentCallback, capacity, selectableItems]);

  const activeSearch = request.scopeIdentity === scopeIdentity && !authLoading ? request.search : '';
  const onSearch = useCallback((value: string) => {
    if (!principalKey || !isCurrentCallback() || typeof value !== 'string' ||
        Array.from(value).length > 160 || /[\u0000-\u001f\u007f-\u009f]/u.test(value)) return;
    // Reject lone surrogate code points before URI encoding.
    try { encodeURIComponent(value); } catch { return; }
    const search = value.trim();
    generationRef.current += 1;
    setSelectedSourceIds([]);
    setPage(null);
    setErrorState(null);
    setRequest(previous => ({ scopeIdentity, principalKey, cursor: null, search, generation: previous.generation + 1 }));
  }, [principalKey, isCurrentCallback, scopeIdentity]);

  const onRefresh = useCallback(() => {
    if (!principalKey || !isCurrentCallback()) return;
    generationRef.current += 1;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      scopeIdentity,
      principalKey,
      cursor: null,
      search: activeSearch,
      generation: value.generation + 1,
    }));
  }, [principalKey, isCurrentCallback, activeSearch, scopeIdentity]);

  const onNextPage = useCallback((cursor: string) => {
    if (
      !isCurrentCallback() || !principalKey || !currentPage ||
      currentPage.generation !== generationRef.current || loading || currentError ||
      !currentPage.has_more || currentPage.next_cursor !== cursor
    ) return;
    generationRef.current += 1;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      scopeIdentity,
      principalKey,
      cursor,
      search: activeSearch,
      generation: value.generation + 1,
    }));
  }, [principalKey, currentPage, loading, currentError, isCurrentCallback, activeSearch, scopeIdentity]);

  const props: FileExplorerInventoryProps = {
    authorized: Boolean(currentPage && !currentError),
    maxSelection: capacity,
    items: selectableItems,
    loading: Boolean(principalKey && !authLoading && (loading || (!currentPage && !currentError))),
    error: currentError,
    selectedSourceIds: currentPage && !currentError && !capacityChanged && effectiveSelection.length <= capacity ? effectiveSelection : [],
    onSelect,
    onRefresh,
    search: activeSearch,
    onSearch: principalKey && !authLoading ? onSearch : undefined,
    hasMore: currentPage?.has_more || false,
    nextCursor: currentPage?.next_cursor || null,
    onNextPage,
    pageKey: principalKey + ':' + (currentPage?.generation ?? 'pending') + ':' + request.generation,
  };

  const selectedAnalysisSources = mode === 'analysis' && currentPage && !currentError && !loading
    ? props.selectedSourceIds.flatMap((id) => {
      const item = currentPage.items.find((entry) => entry.source_id === id);
      return item ? [{ source_id: item.source_id, revision: item.revision, name: item.name }] : [];
    })
    : [];
  const selectedDraftSources = mode === 'selection' && currentPage && !currentError && !loading
    ? props.selectedSourceIds.flatMap(id => {
      const item = currentPage.items.find(entry => entry.source_id === id);
      return item ? [{ source_id: item.source_id, revision: item.revision }] : [];
    })
    : [];
  const selectionKey = props.pageKey + ':' +
    selectedAnalysisSources.map((source) => source.source_id + ':' + source.revision).join('|');

  const panel = selectedAnalysisSources.length > 0 ? (
    <ContentIntelligenceSelectionPanel
      key={selectionKey}
      sources={selectedAnalysisSources}
      maxSelection={props.maxSelection}
      onRefreshInventory={onRefresh}
    />
  ) : null;

  return (
    <>
      {children(props)}
      {mode === 'selection' && onAttach && selectedDraftSources.length > 0 && (
        <button type="button" className="m-2 min-h-11 rounded-lg border border-input px-3 text-sm"
          onClick={() => {
            if (!isCurrentCallback() || !currentPage || currentPage.generation !== generationRef.current) return;
            if (selectedDraftSources.length > capacity) return;
            onAttach(selectedDraftSources);
          }}>
          Attach selected files ({selectedDraftSources.length})
        </button>
      )}
      {mode === 'analysis' && (renderAnalysis ? renderAnalysis(panel, props) : panel)}
    </>
  );
}
