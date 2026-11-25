'use client';

import React, { useId, useLayoutEffect, useMemo, useRef, useState } from 'react';

/**
 * Reusable, controlled File Explorer extension UI.
 *
 * The host must supply verified inventory and callbacks after authorization.
 * A selected source is only a reference, NOT permission to access file bytes.
 * This component does not fetch files or mint tokens.
 */
export interface ExplorerItem {
  source_id: string;
  parent_id: string | null;
  kind: 'file' | 'folder';
  name: string;
  revision: string;
  size_bytes: number;
  sha256: string | null;
  organization_revision?: string;
}

export interface ExplorerSelection {
  source_id: string;
  revision: string;
  sha256: string | null;
  kind: 'file' | 'folder';
}

export type ExplorerOperation = 'file_explorer.folder.create' | 'file_explorer.folder.rename'
  | 'file_explorer.folder.move' | 'file_explorer.artifact.move' | 'file_explorer.folder.delete';
export type ExplorerCapability = 'available' | 'denied' | 'unavailable';
export type ExplorerMutation =
  | { action: 'create'; name: string }
  | { action: 'rename'; sourceId: string; expectedRevision: string; name: string }
  | { action: 'move'; sourceId: string; expectedRevision: string; destinationId: string | null }
  | { action: 'delete'; sourceId: string; expectedRevision: string };
export interface ExplorerDestinationBrowser {
  sourceId: string;
  expectedRevision: string;
  parentId: string | null;
  breadcrumbs: { folder_id: string; name: string }[];
  folders: { folder_id: string; name: string }[];
  loading: boolean;
  error: string | null;
  canConfirm: boolean;
  hasMore: boolean;
  onNavigate: (folderId: string | null) => void;
  onNext: () => void;
  onCancel: () => void;
}

export interface ExplorerManagement {
  capabilities: Partial<Record<ExplorerOperation, ExplorerCapability>>;
  capabilityStatus?: 'checking' | 'ready' | 'unavailable';
  busy: boolean;
  message: string | null;
  onMutate: (mutation: ExplorerMutation) => void;
  onBrowseDestination?: (sourceId: string, expectedRevision: string) => void;
  destination?: ExplorerDestinationBrowser;
}

export interface FileExplorerProps {
  authorized?: boolean;
  items?: ExplorerItem[];
  loading?: boolean;
  error?: string | null;
  selectedSourceIds?: string[];
  multiSelect?: boolean;
  maxSelection?: number;
  onSelect?: (references: ExplorerSelection[]) => void;
  onRefresh?: () => void;
  /** Host-owned server filename search, separate from the displayed-page filter. */
  search?: string;
  onSearch?: (query: string) => void;
  /** The host owns pagination state and must reject stale/out-of-order responses. */
  hasMore?: boolean;
  nextCursor?: string | null;
  onNextPage?: (cursor: string) => void;
  /** Change this on every authorized page or identity/scope transition. */
  pageKey?: string;
  management?: ExplorerManagement;
  hierarchy?: {
    parentId: string | null;
    breadcrumbs: { folder_id: string; name: string }[];
    hasMoreFolders: boolean;
    nextFolderId: string | null;
    onNavigate?: (folderId: string | null) => void;
    onNextFolders?: (folderId: string) => void;
  };
}

const LEGACY_MAX_SELECTION = 12;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

function validSource(value: unknown): value is ExplorerItem {
  if (value === null || typeof value !== 'object') return false;
  const entry = value as Partial<ExplorerItem>;
  return typeof entry.source_id === 'string' &&
    ID_PATTERN.test(entry.source_id) &&
    (entry.parent_id === null ||
      (typeof entry.parent_id === 'string' && ID_PATTERN.test(entry.parent_id))) &&
    entry.source_id !== entry.parent_id &&
    (entry.kind === 'file' || entry.kind === 'folder') &&
    typeof entry.name === 'string' &&
    entry.name.length > 0 &&
    entry.name.length <= 256 &&
    typeof entry.revision === 'string' &&
    entry.revision.length > 0 &&
    typeof entry.size_bytes === 'number' &&
    Number.isSafeInteger(entry.size_bytes) &&
    Number(entry.size_bytes) >= 0 &&
    (entry.sha256 === null ||
      (typeof entry.sha256 === 'string' && /^[a-f0-9]{64}$/.test(entry.sha256)));
}

function prettyBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function FileExplorerView({
  authorized = false,
  items,
  loading = false,
  error = null,
  selectedSourceIds,
  multiSelect = true,
  maxSelection = LEGACY_MAX_SELECTION,
  onSelect,
  onRefresh,
  search = '',
  onSearch,
  hasMore = false,
  nextCursor = null,
  onNextPage,
  hierarchy,
  management,
  onPageTransition,
}: FileExplorerProps & { onPageTransition?: () => void }) {
  const [parentId, setParentId] = useState<string | null>(null);
  const [localSelection, setLocalSelection] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [searchDraft, setSearchDraft] = useState(search);
  const searchId = useId();
  const [edit, setEdit] = useState<{ action: ExplorerMutation['action']; item?: ExplorerItem } | null>(null);
  const [name, setName] = useState('');
  const destination = management?.destination;
  const busy = management?.busy === true;
  const editing = edit !== null;
  const headingId = useId();
  const capabilityId = useId();
  const editorRef = useRef<HTMLFormElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef(false);
  const destinationHeadingRef = useRef<HTMLParagraphElement>(null);
  useLayoutEffect(() => {
    if (edit) {
      if (edit.action === 'create' || edit.action === 'rename') nameRef.current?.focus();
      else editorRef.current?.focus();
    } else if (restoreFocus.current) {
      restoreFocus.current = false;
      if (openerRef.current?.isConnected && !openerRef.current.disabled) openerRef.current.focus();
    }
  }, [edit]);
  function closeEditor() {
    destination?.onCancel();
    restoreFocus.current = true;
    setEdit(null);
  }
  const can = (operation: ExplorerOperation) => management?.capabilities[operation] === 'available';
  function openEditor(trigger: HTMLButtonElement, action: ExplorerMutation['action'], item?: ExplorerItem) {
    if (busy || editing) return;
    openerRef.current = trigger;
    setName(action === 'rename' ? item?.name ?? '' : '');
    if (action === 'move' && item?.organization_revision) {
      management?.onBrowseDestination?.(item.source_id, item.organization_revision);
    } else {
      destination?.onCancel();
    }
    setEdit({ action, item });
  }
  const editOperation: ExplorerOperation | null = !edit ? null :
    edit.action === 'create' ? 'file_explorer.folder.create' :
    edit.action === 'rename' ? 'file_explorer.folder.rename' :
    edit.action === 'delete' ? 'file_explorer.folder.delete' :
    edit.item?.kind === 'file' ? 'file_explorer.artifact.move' : 'file_explorer.folder.move';
  const validName = Boolean(name.trim()) && name === name.trim() &&
    name.length <= 256 && !/[\x00-\x1f\x7f-\x9f]/.test(name);
  const canSubmit = Boolean(edit && editOperation && can(editOperation) && !busy &&
    ((edit.action === 'create' || edit.action === 'rename') ? validName :
      edit.action === 'move' ? destination?.canConfirm && destination.sourceId === edit.item?.source_id &&
        destination.expectedRevision === edit.item?.organization_revision : true));
  function submitEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!edit || !management || !canSubmit) return;
    onPageTransition?.();
    const item = edit.item;
    if (edit.action === 'create' && can('file_explorer.folder.create') && name.trim()) {
      management.onMutate({ action: 'create', name: name.trim() });
    } else if (item?.organization_revision) {
      const evidence = { sourceId: item.source_id, expectedRevision: item.organization_revision };
      if (edit.action === 'rename' && can('file_explorer.folder.rename') && name.trim()) {
        management.onMutate({ action: 'rename', ...evidence, name: name.trim() });
      } else if (edit.action === 'delete' && can('file_explorer.folder.delete')) {
        management.onMutate({ action: 'delete', ...evidence });
      } else if (edit.action === 'move' && can(item.kind === 'folder' ? 'file_explorer.folder.move' : 'file_explorer.artifact.move')) {
        if (!destination?.canConfirm || destination.sourceId !== item.source_id ||
            destination.expectedRevision !== item.organization_revision) return;
        management.onMutate({ action: 'move', ...evidence, destinationId: destination.parentId });
      }
    }
    setEdit(null);
  }
  const pageEvidenceValid = typeof hasMore === 'boolean' && (
    hasMore
      ? typeof nextCursor === 'string' && nextCursor.length > 0 &&
        nextCursor.length <= 768 && typeof onNextPage === 'function'
      : nextCursor === null
  );

  function clearSelections() {
    setLocalSelection([]);
    onSelect?.([]);
  }

  function refresh() {
    if (busy || editing) return;
    clearSelections();
    onPageTransition?.();
    onRefresh?.();
  }

  function nextPage() {
    if (!busy && !editing && !loading && !error && authorized && pageEvidenceValid && hasMore && nextCursor) {
      clearSelections();
      setParentId(null);
      setFilter('');
      onPageTransition?.();
      onNextPage?.(nextCursor);
    }
  }

  const inventory = useMemo(() => {
    if (!authorized || !Array.isArray(items) || items.length > 200) return null;
    const unique = new Set<string>();
    const valid: ExplorerItem[] = [];
    for (const item of items) {
      if (!validSource(item) || unique.has(item.source_id)) return null;
      unique.add(item.source_id);
      valid.push(item);
    }
    return valid;
  }, [authorized, items]);
  const entries = inventory ?? [];
  const byId = useMemo(
    () => new Map(entries.map((item) => [item.source_id, item])),
    [entries],
  );
  const currentParent = hierarchy ? hierarchy.parentId : (parentId !== null && byId.get(parentId)?.kind === 'folder'
    ? parentId
    : null);
  const folder = currentParent === null ? null : byId.get(currentParent);
  const visible = useMemo(() => entries
    .filter((item) => item.parent_id === currentParent &&
      item.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase()))
    .sort((a, b) => Number(a.kind === 'file') - Number(b.kind === 'file') ||
      a.name.localeCompare(b.name) || a.source_id.localeCompare(b.source_id)),
    [entries, currentParent, filter]);
  const selected = (selectedSourceIds ?? localSelection).filter((id) => byId.has(id) && (!hierarchy || byId.get(id)?.kind === 'file'));
  const limit = Number.isSafeInteger(maxSelection) && maxSelection >= 0 && maxSelection <= 200 ? maxSelection : 0;
  const selectionSet = new Set(selected.slice(0, limit));

  function navigate(id: string | null) {
    if (busy || editing) return;
    clearSelections();
    setFilter('');
    if (hierarchy) { onPageTransition?.(); hierarchy.onNavigate?.(id); }
    else setParentId(id);
  }

  function select(item: ExplorerItem) {
    if (busy || editing || limit === 0 || (hierarchy && item.kind !== 'file') ||
        (multiSelect && !selectionSet.has(item.source_id) && selectionSet.size >= limit)) return;
    const next = multiSelect
      ? (selectionSet.has(item.source_id)
        ? selected.filter((id) => id !== item.source_id)
        : [...selected, item.source_id].slice(0, limit))
      : [item.source_id];
    if (selectedSourceIds === undefined) setLocalSelection(next);
    const references = next.flatMap((id) => {
      const entry = byId.get(id);
      return entry ? [{
        source_id: entry.source_id,
        revision: entry.revision,
        sha256: entry.sha256,
        kind: entry.kind,
      }] : [];
    });
    // Selection is a presentation event, not a backend authorization receipt.
    onSelect?.(references);
  }

  const validSearch = Array.from(searchDraft).length <= 160 &&
    !/[\u0000-\u001f\u007f-\u009f]/u.test(searchDraft) &&
    !/[\uD800-\uDFFF]/u.test(searchDraft);
  const searchForm = onSearch && <form aria-label="Search authorized filenames"
    className="flex flex-wrap items-end gap-2 w-full min-w-0"
    onSubmit={event => {
      event.preventDefault();
      if (busy || editing || loading || !validSearch) return;
      onPageTransition?.();
      onSearch(searchDraft);
    }}>
    <label htmlFor={searchId} className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
      {hierarchy ? 'Search filenames in this folder' : 'Search authorized filenames'}
      <input id={searchId} type="search" value={searchDraft}
        onChange={event => setSearchDraft(event.target.value)}
        disabled={busy || editing || loading}
        aria-invalid={!validSearch} className="min-w-0 rounded border bg-background px-3 py-2"
        placeholder="Search filenames…" />
    </label>
    <button type="submit" disabled={busy || editing || loading || !validSearch}
      className="rounded border px-3 py-2 text-sm">Search</button>
    {search && <button type="button" disabled={busy || editing || loading}
      onClick={() => { setSearchDraft(''); onPageTransition?.(); onSearch(''); }}
      className="rounded border px-3 py-2 text-sm">Clear search</button>}
    {!validSearch && <p role="alert" className="w-full text-xs">Use at most 160 characters without control characters.</p>}
    {search && <p role="status" className="w-full break-words text-xs">Filename results for “{search}”{hierarchy ? ' in this folder. Folder navigation remains visible.' : '.'}</p>}
  </form>;
  if (!authorized || Boolean(error) || !pageEvidenceValid || (!loading && inventory === null)) {
    return <section role="alert" className="flex flex-col items-start gap-3 rounded-lg border p-6 text-sm text-muted-foreground">
      {loading ? <p role="status">Loading authorized file inventory…</p> :
        <p>File Explorer is unavailable. No authorized file inventory has been supplied by KAREN.</p>}
      {error && <p className="text-destructive">{error}</p>}
      {error && <p>Refresh to reload authorized inventory from the root.</p>}
      {error && searchForm}
      {authorized && !pageEvidenceValid && <p className="text-destructive">Invalid host pagination evidence.</p>}
      {(authorized || Boolean(error)) && onRefresh && <button type="button" className="rounded border px-3 py-2 text-sm" onClick={refresh}>Refresh</button>}
    </section>;
  }

  return <section className="flex min-h-[320px] flex-col gap-4 rounded-lg border bg-background p-4" aria-label="Shared File Explorer">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">File Explorer</h2>
        <p className="text-xs text-muted-foreground">
          References only. File access is checked again by the consuming service.
        </p>
      </div>
      {onRefresh && <button type="button" disabled={busy || editing} className="rounded border px-3 py-2 text-sm" onClick={refresh}>Refresh</button>}
    </header>
    {management && <div className="flex flex-wrap items-center gap-2">
      <button type="button" aria-describedby={capabilityId} disabled={busy || editing || !can('file_explorer.folder.create')} className="rounded border px-3 py-2 text-sm disabled:opacity-50" onClick={event => openEditor(event.currentTarget, 'create')}>New folder</button>
      <p id={capabilityId} role="status" className="w-full text-xs text-muted-foreground">
        {management.capabilityStatus === 'checking' ? 'Checking organization permissions…' :
          management.capabilityStatus === 'unavailable' ? 'Organization controls unavailable. Refresh to recheck.' :
          ([
            ['file_explorer.folder.create', 'Create folder'],
            ['file_explorer.folder.rename', 'Rename folder'],
            ['file_explorer.folder.move', 'Move folder'],
            ['file_explorer.artifact.move', 'Move file'],
            ['file_explorer.folder.delete', 'Delete empty folder'],
          ] as [ExplorerOperation, string][]).filter(([operation]) => !can(operation)).map(([operation, label]) =>
            label + ': ' + (management.capabilities[operation] === 'denied' ? 'permission denied' : 'unavailable')).join(' · ') ||
          'Organization controls available. Each change is checked again.'}
      </p>
      {management.message && <p role="status" className="text-sm">{management.message}</p>}
      {busy && <p role="status" className="text-sm">Saving organization change…</p>}
    </div>}
    {edit && management && <form ref={editorRef} tabIndex={-1} aria-label="Confirm organization change" aria-describedby={headingId}
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeEditor(); } }}
      onSubmit={submitEdit} className="flex flex-col gap-3 rounded-lg border p-3">
      <h3 id={headingId} className="font-medium">{edit.action === 'create' ? 'Create folder' : edit.action === 'rename' ? 'Rename folder' : edit.action === 'move' ? 'Move ' + (edit.item?.name ?? '') : 'Delete empty folder'}</h3>
      {(edit.action === 'create' || edit.action === 'rename') && <label className="flex flex-col gap-1 text-sm">Folder name<input ref={nameRef} required maxLength={256} value={name} onChange={event => setName(event.target.value)} className="rounded border bg-background p-2" /></label>}
      {edit.action === 'move' && <section aria-label="Move destination browser" className="flex flex-col gap-2 rounded border p-2">
        <p ref={destinationHeadingRef} tabIndex={-1} className="text-sm">Choose a destination folder for {edit.item?.name}.</p>
        <nav aria-label="Destination location" className="flex flex-wrap gap-2">
          <button type="button" disabled={!destination || busy} onClick={() => destination?.onNavigate(null)} className="rounded border px-2 py-1">Destination root</button>
          {destination?.breadcrumbs.map(crumb => <button type="button" key={crumb.folder_id}
            onClick={() => destination.onNavigate(crumb.folder_id)} disabled={busy}
            aria-current={crumb.folder_id === destination.parentId ? 'location' : undefined}
            className="rounded border px-2 py-1">{crumb.name}</button>)}
        </nav>
        {destination?.loading && <p role="status">Loading destination folders…</p>}
        {destination?.error && <p role="alert">{destination.error} Return to destination root to retry.</p>}
        {destination && !destination.loading && !destination.error && <ul aria-label="Destination folders" className="flex flex-col gap-1">
          {destination.folders.map(folder => <li key={folder.folder_id}>
            <button type="button" className="rounded border px-2 py-1 text-left" disabled={busy}
              onClick={() => { destinationHeadingRef.current?.focus(); destination.onNavigate(folder.folder_id); }} aria-label={'Browse destination ' + folder.name}>{folder.name}</button>
          </li>)}
          {destination.folders.length === 0 && <li className="text-sm text-muted-foreground">No eligible subfolders on this page.</li>}
        </ul>}
        {destination?.hasMore && <button type="button" disabled={destination.loading || busy} onClick={() => { destinationHeadingRef.current?.focus(); destination.onNext(); }} className="rounded border px-2 py-1">Next destination folder page</button>}
        <p role="status" className="text-sm">Selected destination: {destination?.canConfirm ? destination.breadcrumbs[destination.breadcrumbs.length - 1]?.name ?? 'Root' : 'Not verified'}</p>
      </section>}
      {edit.action === 'delete' && <p className="text-sm">Delete {edit.item?.name}? Only empty folders can be deleted, including no archived files. File contents will not be deleted.</p>}
      <div className="flex flex-wrap gap-2"><button type="submit" disabled={!canSubmit} className="rounded border px-3 py-2 text-sm">Confirm {edit.action}</button><button type="button" onClick={closeEditor} className="rounded border px-3 py-2 text-sm">Cancel</button></div>
    </form>}
    <nav aria-label="Folder location" className="flex flex-wrap items-center gap-2 text-sm">
      <button type="button" disabled={busy || editing} className="rounded border px-3 py-2" onClick={() => navigate(null)}>Root</button>
      {hierarchy?.breadcrumbs.map(crumb => <React.Fragment key={crumb.folder_id}>
        <span aria-hidden="true">/</span>
        <button type="button" className="min-w-0 truncate rounded border px-2 py-1" disabled={busy || editing} onClick={() => navigate(crumb.folder_id)}
          aria-current={crumb.folder_id === hierarchy.parentId ? 'location' : undefined}>{crumb.name}</button>
      </React.Fragment>)}
      {!hierarchy && folder && <>
        <span aria-hidden="true">/</span>
        <span className="truncate">{folder.name}</span>
        <button type="button" className="rounded border px-3 py-2" onClick={() => {
          setParentId(folder.parent_id && byId.has(folder.parent_id) ? folder.parent_id : null);
          setFilter('');
        }}>Up</button>
      </>}
    </nav>
    {searchForm}
    <label className="flex flex-col gap-1 text-sm">
      Filter current folder
      <input className="rounded border bg-background px-3 py-2" type="search" disabled={busy || editing} value={filter}
        onChange={(event) => setFilter(event.target.value)} placeholder="Filter this page…" />
    </label>
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm text-destructive">{error}</p>}
    {loading ? <p role="status" className="py-8 text-center text-sm">Loading authorized file inventory…</p>
      : visible.length === 0 ? <p role="status" className="py-8 text-center text-sm text-muted-foreground">No files or folders in this view.</p>
      : <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Files and folders">
        {visible.map((item) => <li key={item.source_id} className="flex min-w-0 flex-wrap items-center gap-2 rounded border p-2">
          {(!hierarchy || item.kind === 'file') && <input type={multiSelect ? 'checkbox' : 'radio'} name="file-explorer-selection"
            aria-label={'Select ' + item.name} checked={selectionSet.has(item.source_id)} disabled={busy || editing || loading || Boolean(error) || limit === 0 ||
              (multiSelect && !selectionSet.has(item.source_id) && selectionSet.size >= limit)}
            onChange={() => select(item)} />}
          {item.kind === 'folder'
            ? <button type="button" className="min-w-0 flex-1 truncate text-left text-sm font-medium underline"
                disabled={busy || editing} onClick={() => navigate(item.source_id)} aria-label={'Open folder ' + item.name}>
                📁 {item.name}</button>
            : <div className="min-w-0 flex-1">
                <p className="truncate text-sm" title={item.name}>📄 {item.name}</p>
                <p className="text-xs text-muted-foreground">{prettyBytes(item.size_bytes)}</p>
              </div>}
          {management && hierarchy && item.organization_revision && <div className="flex flex-wrap gap-1 text-xs">
            {item.kind === 'folder' && <button type="button" disabled={busy || editing || !can('file_explorer.folder.rename')} aria-describedby={capabilityId} onClick={event => openEditor(event.currentTarget, 'rename', item)} aria-label={'Rename ' + item.name} className="rounded border px-2 py-1 disabled:opacity-50">Rename</button>}
            <button type="button" disabled={busy || editing || !can(item.kind === 'folder' ? 'file_explorer.folder.move' : 'file_explorer.artifact.move')} aria-describedby={capabilityId} onClick={event => openEditor(event.currentTarget, 'move', item)} aria-label={'Move ' + item.name} className="rounded border px-2 py-1 disabled:opacity-50">Move</button>
            {item.kind === 'folder' && <button type="button" disabled={busy || editing || !can('file_explorer.folder.delete')} aria-describedby={capabilityId} onClick={event => openEditor(event.currentTarget, 'delete', item)} aria-label={'Delete ' + item.name} className="rounded border px-2 py-1 disabled:opacity-50">Delete</button>}
          </div>}
        </li>)}
      </ul>}
    <footer className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
      <span>{selectionSet.size} selected · {visible.length} shown on this page · Maximum {limit} selections</span>
      {hierarchy?.hasMoreFolders && hierarchy.nextFolderId && <button type="button" className="rounded border px-3 py-2 text-sm"
        disabled={busy || editing || loading || Boolean(error)} onClick={() => { if (!busy && !editing) { clearSelections(); onPageTransition?.(); hierarchy.onNextFolders?.(hierarchy.nextFolderId!); } }}>Next folder page</button>}
      {hasMore && <button type="button" className="rounded border px-3 py-2 text-sm"
        disabled={loading || Boolean(error) || !pageEvidenceValid || busy || editing} onClick={nextPage}>{hierarchy ? 'Next file page' : 'Next page'}</button>}
    </footer>
  </section>;
}

export function SharedFileExplorer(props: FileExplorerProps) {
  // A new host-issued page identity resets local folder/filter/selection state.
  // Authorization and stale-response rejection remain host responsibilities.
  const region = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<{ key: string; scope: string } | null>(null);
  const key = props.pageKey ?? 'initial';
  const scope = key.slice(0, key.lastIndexOf(':'));
  useLayoutEffect(() => {
    const pending = pendingFocus.current;
    if (!pending) return;
    if (pending.scope !== scope) { pendingFocus.current = null; return; }
    if (key !== pending.key && (props.authorized || props.error)) {
      pendingFocus.current = null;
      region.current?.focus();
    }
  }, [key, scope, props.authorized, props.error]);
  return <div ref={region} tabIndex={-1} aria-label="File Explorer content" className="min-w-0 max-w-full">
    <FileExplorerView key={props.pageKey ?? 'initial'} {...props}
      onPageTransition={() => { pendingFocus.current = { key, scope }; }} />
  </div>;
}

export default function FileExplorerPage(props: FileExplorerProps) {
  return <SharedFileExplorer {...props} />;
}
