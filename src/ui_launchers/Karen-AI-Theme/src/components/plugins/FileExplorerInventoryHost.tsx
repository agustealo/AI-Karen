'use client';

/**
 * Authenticated owner inventory host shared by governed document consumers.
 *
 * Only the canonical API authorizes inventory reads. This component receives
 * no storage credentials and cannot grant read access to selected references.
 * Requests made by an earlier principal or page generation never update state.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { ContentIntelligenceSelectionPanel } from './ContentIntelligenceSelectionPanel';
import type { ExplorerCapability, ExplorerManagement, ExplorerMutation, ExplorerOperation } from '@/plugin_repo/file-explorer/FileExplorerPage';

interface ExplorerItem {
  source_id: string;
  parent_id: string | null;
  kind: 'file' | 'folder';
  name: string;
  revision: string;
  size_bytes: number;
  sha256: string | null;
  organization_revision?: string;
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

interface HierarchyLocation {
  parentId: string | null;
  breadcrumbs: { folder_id: string; name: string }[];
  hasMoreFolders: boolean;
  nextFolderId: string | null;
  onNavigate?: (folderId: string | null) => void;
  onNextFolders?: (folderId: string) => void;
}

interface ScopedPage extends InventoryPage {
  hierarchy?: HierarchyLocation;
  principalKey: string;
  generation: number;
}

interface PageRequest {
  principalKey: string;
  cursor: string | null;
  parentId?: string | null;
  afterFolderId?: string | null;
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
  hierarchy?: HierarchyLocation;
  management?: ExplorerManagement;
}

export type InventoryConsumer = 'file-explorer' | 'content-intelligence';

const INVENTORY_ENDPOINTS: Record<InventoryConsumer, string> = {
  'file-explorer': '/api/plugins/file-explorer/inventory',
  'content-intelligence': '/api/plugins/content-intelligence/inventory',
};

const HEX_SHA256 = /^[a-f0-9]{64}$/;
const MAX_PAGE_SIZE = 200;
const MAX_CURSOR_LENGTH = 768;

function assertInventoryPage(data: unknown, parentId: string | null = null): InventoryPage {
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
      item.parent_id !== parentId ||
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
      parent_id: parentId,
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

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const validUuid = (value: unknown): value is string => typeof value === 'string' && UUID.test(value);
const validRevision = (value: unknown): value is string =>
  typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value) &&
  (value.length < 19 || value <= '9223372036854775806');

function assertHierarchyPage(data: unknown, parentId: string | null, folderCursor: string | null, fileCursor: string | null):
  InventoryPage & { hierarchy: HierarchyLocation } {
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid file inventory response');
  const page = data as Record<string, unknown>;
  if (page.available !== true) throw new Error('File hierarchy unavailable');
  if (!Array.isArray(page.folders) || page.folders.length > 100 ||
      !Array.isArray(page.breadcrumbs) || page.breadcrumbs.length > 64 ||
      !Array.isArray(page.files) || page.files.length > 100 ||
      typeof page.has_more !== 'boolean' ||
      (page.has_more ? !validUuid(page.next_folder_id) || page.next_folder_id === folderCursor ||
          page.folders.length === 0 || page.folders[page.folders.length - 1]?.folder_id !== page.next_folder_id
        : page.next_folder_id !== null) ||
      (page.files_has_more === true && page.next_file_cursor === fileCursor)) {
    throw new Error('Invalid file inventory response');
  }
  function folder(raw: unknown, expectedParent: string | null): ExplorerItem {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid file inventory response');
    const item = raw as Record<string, unknown>;
    if (!validUuid(item.folder_id) || item.folder_id === expectedParent ||
        item.parent_folder_id !== expectedParent || typeof item.name !== 'string' ||
        !item.name || item.name.length > 256 || !validRevision(item.revision)) {
      throw new Error('Invalid file inventory response');
    }
    return { source_id: item.folder_id, parent_id: expectedParent, kind: 'folder',
      name: item.name, revision: item.revision, size_bytes: 0, sha256: null,
      organization_revision: item.revision };
  }
  const breadcrumbs: HierarchyLocation['breadcrumbs'] = [];
  const seen = new Set<string>();
  let previous: string | null = null;
  for (const raw of page.breadcrumbs) {
    const item = folder(raw, previous);
    if (seen.has(item.source_id)) throw new Error('Invalid file inventory response');
    seen.add(item.source_id);
    breadcrumbs.push({ folder_id: item.source_id, name: item.name });
    previous = item.source_id;
  }
  if (previous !== parentId) throw new Error('Invalid file inventory response');
  const folders = page.folders.map(raw => folder(raw, parentId));
  const files = assertInventoryPage({
    items: page.files, has_more: page.files_has_more, next_cursor: page.next_file_cursor,
    inventory_semantics: 'owner_metadata_page_not_live_acl',
    request_id: page.request_id, correlation_id: page.correlation_id,
  }, parentId);
  for (let i = 0; i < files.items.length; i++) {
    const revision = page.files[i]?.organization_revision;
    if (!validUuid(files.items[i].source_id) || !validRevision(revision)) {
      throw new Error('Invalid file inventory response');
    }
    files.items[i].organization_revision = revision;
  }
  const items = [...folders, ...files.items];
  for (const item of items) {
    if (seen.has(item.source_id)) throw new Error('Invalid file inventory response');
    seen.add(item.source_id);
  }
  return { ...files, items, hierarchy: { parentId, breadcrumbs,
    hasMoreFolders: page.has_more, nextFolderId: page.next_folder_id as string | null } };
}

const OPERATIONS: ExplorerOperation[] = [
  'file_explorer.folder.create', 'file_explorer.folder.rename', 'file_explorer.folder.move',
  'file_explorer.artifact.move', 'file_explorer.folder.delete',
];

function capabilityResponse(data: unknown): ExplorerManagement['capabilities'] {
  if (!data || typeof data !== 'object') return {};
  const value = data as Record<string, unknown>;
  if (value.browse !== 'available' || value.semantics !== 'preflight_not_resource_authorization' ||
      typeof value.request_id !== 'string' || !value.request_id ||
      typeof value.correlation_id !== 'string' || !value.correlation_id ||
      !value.operations || typeof value.operations !== 'object') return {};
  const operations = value.operations as Record<string, unknown>;
  const result: Partial<Record<ExplorerOperation, ExplorerCapability>> = {};
  for (const operation of OPERATIONS) {
    const state = operations[operation];
    if (state !== 'available' && state !== 'denied' && state !== 'unavailable') return {};
    result[operation] = state;
  }
  return result;
}

function assertMutationReceipt(data: unknown, mutation: ExplorerMutation, parent: string | null, item?: ExplorerItem) {
  if (!data || typeof data !== 'object') throw new Error('Unconfirmed organization change');
  const result = data as Record<string, unknown>;
  if (typeof result.request_id !== 'string' || !result.request_id ||
      typeof result.correlation_id !== 'string' || !result.correlation_id) throw new Error('Unconfirmed organization change');
  const matchesRevision = (revision: unknown, expected: string) => validRevision(revision) &&
    (revision === expected || BigInt(revision) === BigInt(expected) + BigInt(1));
  if (mutation.action === 'delete') {
    if (result.deleted === true && result.folder_id === mutation.sourceId) return;
  } else if (mutation.action === 'move') {
    if (result.source_id === mutation.sourceId && result.kind === (item?.kind === 'file' ? 'artifact' : 'folder') &&
        result.parent_folder_id === mutation.destinationId &&
        matchesRevision(result.organization_revision, mutation.expectedRevision)) return;
  } else if (result.folder && typeof result.folder === 'object') {
    const folder = result.folder as Record<string, unknown>;
    if (validUuid(folder.folder_id) && folder.parent_folder_id === parent && folder.name === mutation.name &&
        (mutation.action === 'create' ? folder.revision === '1' :
          folder.folder_id === mutation.sourceId && matchesRevision(folder.revision, mutation.expectedRevision))) return;
  }
  throw new Error('Unconfirmed organization change');
}

export function FileExplorerInventoryHost({
  children,
  mode = 'analysis',
  consumer = 'file-explorer',
  hierarchy = consumer === 'file-explorer',
  onAttach,
  renderAnalysis,
}: {
  children: (props: FileExplorerInventoryProps) => ReactNode;
  /** Selection mode exposes metadata only; it never mounts the analysis workflow. */
  mode?: 'analysis' | 'selection';
  /** Trusted UI composition selects a fixed endpoint; the server authorizes it. */
  consumer?: InventoryConsumer;
  /** Flat inventory remains explicit for existing non-hierarchy consumers. */
  hierarchy?: boolean;
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
      hierarchy ? 'hierarchy' : 'flat',
      user.tenant_id,
      user.user_id,
      [...(user.roles || [])].sort().join(','),
      [...(user.permissions || [])].sort().join(','),
    ].join('|');
  }, [isAuthenticated, user, consumer, hierarchy]);

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
  const managementEnabled = hierarchy && consumer === 'file-explorer' && mode === 'analysis';
  const [capability, setCapability] = useState<{ generation: number; operations: ExplorerManagement['capabilities'] } | null>(null);
  const [mutationState, setMutationState] = useState<{ principalKey: string; message: string | null; busy: boolean } | null>(null);
  const mutationRef = useRef<{ generation: number; principalKey: string } | null>(null);

  useEffect(() => {
    // The source is authenticated API truth, never browser-supplied inventory.
    if (!principalKey || authLoading) {
      mutationRef.current = null;
      setMutationState(null);
      setCapability(null);
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
    const parentId = request.principalKey === principalKey ? request.parentId ?? null : null;
    const afterFolderId = request.principalKey === principalKey ? request.afterFolderId ?? null : null;

    setLoading(true);
    setPage(null);
    setErrorState(null);
    setSelectedSourceIds([]);

    const endpoint = hierarchy
      ? '/api/plugins/file-explorer/hierarchy?limit=100' +
        (parentId ? '&parent_folder_id=' + encodeURIComponent(parentId) : '') +
        (afterFolderId ? '&after_folder_id=' + encodeURIComponent(afterFolderId) : '') +
        (cursor ? '&file_cursor=' + encodeURIComponent(cursor) : '')
      : INVENTORY_ENDPOINTS[consumer] + '?limit=100' +
        (cursor ? '&cursor=' + encodeURIComponent(cursor) : '');

    void apiClient.get<unknown>(endpoint)
      .then((data) => {
        if (cancelled || generationRef.current !== generation) return;
        const verified = hierarchy ? assertHierarchyPage(data, parentId, afterFolderId, cursor) : assertInventoryPage(data);
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
  }, [principalKey, authLoading, request, consumer, hierarchy]);

  const currentPage = !authLoading && principalKey && page?.principalKey === principalKey ? page : null;
  const currentError = !authLoading && principalKey && errorState?.principalKey === principalKey ? errorState.message : null;

  useEffect(() => {
    if (!managementEnabled || !currentPage) return;
    let cancelled = false;
    const generation = currentPage.generation;
    void apiClient.get<unknown>('/api/plugins/file-explorer/capabilities')
      .then(data => {
        if (!cancelled && generationRef.current === generation) {
          setCapability({ generation, operations: capabilityResponse(data) });
        }
      })
      .catch(() => {
        if (!cancelled && generationRef.current === generation) setCapability({ generation, operations: {} });
      });
    return () => { cancelled = true; };
  }, [managementEnabled, currentPage]);

  const onSelect = useCallback((references: ExplorerSelection[]) => {
    if (!currentPage || loading || currentError || mutationRef.current?.principalKey === principalKey) {
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
        !item || item.kind !== 'file' ||
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
  }, [currentPage, loading, currentError, principalKey]);

  const onRefresh = useCallback(() => {
    if (!principalKey || mutationRef.current?.principalKey === principalKey) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      principalKey,
      cursor: null,
      parentId: value.principalKey === principalKey ? value.parentId ?? null : null,
      afterFolderId: null,
      generation: value.generation + 1,
    }));
  }, [principalKey]);

  const onNextPage = useCallback((cursor: string) => {
    if (
      !principalKey || !currentPage || loading || currentError || mutationRef.current?.principalKey === principalKey ||
      !currentPage.has_more || currentPage.next_cursor !== cursor
    ) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest((value) => ({
      principalKey,
      cursor,
      parentId: currentPage.hierarchy?.parentId ?? null,
      afterFolderId: value.principalKey === principalKey ? value.afterFolderId ?? null : null,
      generation: value.generation + 1,
    }));
  }, [principalKey, currentPage, loading, currentError]);

  const onNavigate = useCallback((folderId: string | null) => {
    if (!principalKey || !currentPage?.hierarchy || loading || currentError || mutationRef.current?.principalKey === principalKey) return;
    if (folderId !== null &&
        !currentPage.hierarchy.breadcrumbs.some(crumb => crumb.folder_id === folderId) &&
        !currentPage.items.some(item => item.kind === 'folder' && item.source_id === folderId)) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest(value => ({ principalKey, cursor: null, parentId: folderId,
      afterFolderId: null, generation: value.generation + 1 }));
  }, [principalKey, currentPage, loading, currentError]);

  const onNextFolders = useCallback((folderId: string) => {
    if (!principalKey || !currentPage?.hierarchy || loading || currentError || mutationRef.current?.principalKey === principalKey ||
        !currentPage.hierarchy.hasMoreFolders || currentPage.hierarchy.nextFolderId !== folderId) return;
    setSelectedSourceIds([]);
    setPage(null);
    setRequest(value => ({ principalKey,
      cursor: value.principalKey === principalKey ? value.cursor : null,
      parentId: currentPage.hierarchy?.parentId ?? null,
      afterFolderId: folderId, generation: value.generation + 1 }));
  }, [principalKey, currentPage, loading, currentError]);

  const onMutate = useCallback(async (mutation: ExplorerMutation) => {
    if (!managementEnabled || !currentPage?.hierarchy || loading || currentError ||
        generationRef.current !== currentPage.generation ||
        capability?.generation !== currentPage.generation ||
        mutationRef.current?.principalKey === principalKey) return;
    const item = mutation.action === 'create' ? undefined :
      currentPage.items.find(entry => entry.source_id === mutation.sourceId);
    if (mutation.action !== 'create' && (!item || !validRevision(item.organization_revision) ||
        mutation.expectedRevision !== item.organization_revision)) return;
    if ((mutation.action === 'rename' || mutation.action === 'delete') && item?.kind !== 'folder') return;
    if (mutation.action === 'create' || mutation.action === 'rename') {
      if (typeof mutation.name !== 'string' || !mutation.name || mutation.name.length > 256 ||
          mutation.name !== mutation.name.trim() || /[\x00-\x1f\x7f-\x9f]/.test(mutation.name)) return;
    }
    const operation: ExplorerOperation = mutation.action === 'move'
      ? (item?.kind === 'file' ? 'file_explorer.artifact.move' : 'file_explorer.folder.move')
      : mutation.action === 'create' ? 'file_explorer.folder.create'
      : mutation.action === 'rename' ? 'file_explorer.folder.rename' : 'file_explorer.folder.delete';
    if (capability.operations[operation] !== 'available') return;
    const location = currentPage.hierarchy;
    if (mutation.action === 'move' && mutation.destinationId !== null &&
        (mutation.destinationId === item?.source_id || !(
          location.breadcrumbs.some(crumb => crumb.folder_id === mutation.destinationId) ||
          currentPage.items.some(entry => entry.kind === 'folder' && entry.source_id === mutation.destinationId)
        ))) return;
    const token = { generation: currentPage.generation, principalKey };
    mutationRef.current = token;
    setSelectedSourceIds([]);
    setMutationState({ principalKey, busy: true, message: null });
    const prefix = '/api/plugins/file-explorer';
    let message = 'Organization change confirmed. Reloading inventory.';
    try {
      let result: unknown;
      if (mutation.action === 'create') {
        result = await apiClient.post(prefix + '/folders', { name: mutation.name, parent_folder_id: location.parentId });
      } else if (mutation.action === 'rename') {
        result = await apiClient.patch(prefix + '/folders/' + mutation.sourceId, {
          name: mutation.name, expected_revision: mutation.expectedRevision,
        });
      } else if (mutation.action === 'delete') {
        result = await apiClient.delete(prefix + '/folders/' + mutation.sourceId, {
          expected_revision: mutation.expectedRevision,
        });
      } else {
        result = await apiClient.post(prefix + '/move/' + (item?.kind === 'file' ? 'artifact' : 'folder') + '/' + mutation.sourceId, {
          destination_id: mutation.destinationId, expected_revision: mutation.expectedRevision,
        });
      }
      assertMutationReceipt(result, mutation, location.parentId, item);
    } catch (error) {
      const status = error && typeof error === 'object' && 'status' in error ? error.status : null;
      message = status === 409 ? 'Organization conflict. Review the refreshed inventory before trying again.'
        : status === 403 ? 'Organization change denied. Permissions will be checked again.'
        : 'Organization change not confirmed. Review inventory before trying again; no automatic retry.';
    } finally {
      if (mutationRef.current === token) mutationRef.current = null;
      if (generationRef.current === token.generation) {
        setMutationState({ principalKey, busy: false, message });
        setCapability(null);
        setPage(null);
        setRequest(value => ({ principalKey, cursor: null, parentId: location.parentId,
          afterFolderId: null, generation: value.generation + 1 }));
      }
    }
  }, [managementEnabled, currentPage, loading, currentError, capability, principalKey]);

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
    hierarchy: currentPage?.hierarchy ? { ...currentPage.hierarchy, onNavigate, onNextFolders } : undefined,
    management: managementEnabled && currentPage?.hierarchy ? {
      capabilities: capability?.generation === currentPage.generation ? capability.operations : {},
      busy: mutationState?.principalKey === principalKey && mutationState.busy,
      message: mutationState?.principalKey === principalKey ? mutationState.message : null,
      onMutate,
    } : undefined,
  };

  const selectedAnalysisSources = mode === 'analysis' && currentPage && !currentError && !loading
    ? selectedSourceIds.flatMap((id) => {
      const item = currentPage.items.find((entry) => entry.source_id === id);
      return item?.kind === 'file' ? [{ source_id: item.source_id, revision: item.revision, name: item.name }] : [];
    })
    : [];
  const selectedDraftSources = mode === 'selection' && currentPage && !currentError && !loading
    ? selectedSourceIds.flatMap(id => {
      const item = currentPage.items.find(entry => entry.source_id === id);
      return item?.kind === 'file' ? [{ source_id: item.source_id, revision: item.revision }] : [];
    })
    : [];
  const selectionKey = props.pageKey + ':' +
    selectedAnalysisSources.map((source) => source.source_id + ':' + source.revision).join('|');

  const panel = selectedAnalysisSources.length > 0 ? (
    <ContentIntelligenceSelectionPanel
      key={selectionKey}
      sources={selectedAnalysisSources}
      onRefreshInventory={onRefresh}
    />
  ) : null;

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
      {mode === 'analysis' && (renderAnalysis ? renderAnalysis(panel, props) : panel)}
    </>
  );
}
