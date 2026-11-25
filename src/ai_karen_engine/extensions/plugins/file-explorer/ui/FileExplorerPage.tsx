'use client';

import React, { useMemo, useState } from 'react';
import { FileText, Folder, FolderOpen, Search, LayoutGrid, List, ChevronRight } from 'lucide-react';

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
}

export interface ExplorerSelection {
  source_id: string;
  revision: string;
  sha256: string | null;
  kind: 'file' | 'folder';
}

export interface FileExplorerProps {
  authorized?: boolean;
  items?: ExplorerItem[];
  loading?: boolean;
  error?: string | null;
  selectedSourceIds?: string[];
  multiSelect?: boolean;
  onSelect?: (references: ExplorerSelection[]) => void;
  onRefresh?: () => void;
  /** The host owns pagination state and must reject stale/out-of-order responses. */
  hasMore?: boolean;
  nextCursor?: string | null;
  onNextPage?: (cursor: string) => void;
  /** Change this on every authorized page or identity/scope transition. */
  pageKey?: string;
}

const MAX_SELECTION = 24;
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
  onSelect,
  onRefresh,
  hasMore = false,
  nextCursor = null,
  onNextPage,
}: FileExplorerProps) {
  const [parentId, setParentId] = useState<string | null>(null);
  const [localSelection, setLocalSelection] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [layout, setLayout] = useState<'list' | 'grid'>('list');
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
    clearSelections();
    onRefresh?.();
  }

  function nextPage() {
    if (!loading && !error && authorized && pageEvidenceValid && hasMore && nextCursor) {
      clearSelections();
      setParentId(null);
      setFilter('');
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
  const currentParent = parentId !== null && byId.get(parentId)?.kind === 'folder'
    ? parentId
    : null;
  const folder = currentParent === null ? null : byId.get(currentParent);
  const visible = useMemo(() => entries
    .filter((item) => item.parent_id === currentParent &&
      item.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase()))
    .sort((a, b) => Number(a.kind === 'file') - Number(b.kind === 'file') ||
      a.name.localeCompare(b.name) || a.source_id.localeCompare(b.source_id)),
    [entries, currentParent, filter]);
  const selected = (selectedSourceIds ?? localSelection).filter((id) => byId.has(id));
  const selectionSet = new Set(selected);
  const selectionLimit = multiSelect ? MAX_SELECTION : 1;
  const atLimit = multiSelect && selectionSet.size >= selectionLimit;

  function select(item: ExplorerItem) {
    if (!authorized || loading || error || !pageEvidenceValid || inventory === null) return;
    if (atLimit && !selectionSet.has(item.source_id)) return;
    const next = multiSelect
      ? (selectionSet.has(item.source_id)
        ? selected.filter((id) => id !== item.source_id)
        : [...selected, item.source_id])
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

  if (!authorized || Boolean(error) || !pageEvidenceValid || (!loading && inventory === null)) {
    return <section role="alert" className="flex flex-col items-start gap-3 rounded-lg border p-6 text-sm text-muted-foreground">
      {loading ? <p role="status">Loading authorized file inventory…</p> :
        <p>File Explorer is unavailable. No authorized file inventory has been supplied by KAREN.</p>}
      {error && <p className="text-destructive">{error}</p>}
      {authorized && !pageEvidenceValid && <p className="text-destructive">Invalid host pagination evidence.</p>}
      {(authorized || Boolean(error)) && onRefresh && <button type="button" className="rounded border px-3 py-2 text-sm" onClick={refresh}>Refresh</button>}
    </section>;
  }

  return <section className="flex min-h-[320px] min-w-0 flex-col gap-4 rounded-xl border bg-background p-3 sm:p-4" aria-label="Shared File Explorer">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight"><FolderOpen aria-hidden="true" className="h-5 w-5 text-muted-foreground" />File Explorer</h2>
        <p className="text-xs text-muted-foreground">
          References only. File access is checked again by the consuming service.
        </p>
      </div>
      {onRefresh && <button type="button" className="rounded border px-3 py-2 text-sm" onClick={refresh}>Refresh</button>}
    </header>
    <nav aria-label="Folder location" className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg bg-muted/40 p-2 text-sm">
      <button type="button" className="rounded border px-3 py-2" onClick={() => { setParentId(null); setFilter(''); }}>Root</button>
      {folder && <>
        <ChevronRight aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="truncate">{folder.name}</span>
        <button type="button" className="rounded border px-3 py-2" onClick={() => {
          setParentId(folder.parent_id && byId.has(folder.parent_id) ? folder.parent_id : null);
          setFilter('');
        }}>Up</button>
      </>}
    </nav>
    <div className="flex flex-wrap items-end gap-2">
    <label className="flex min-w-0 flex-1 basis-48 flex-col gap-1 text-sm">
      Filter current folder (loaded page only)
      <div className="relative min-w-0">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        <input className="w-full rounded-md border bg-background py-2 pl-9 pr-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" type="search" value={filter}
          onChange={(event) => setFilter(event.target.value)} placeholder="Find files or folders…" />
      </div>
    </label>
    <div role="group" aria-label="Explorer layout" className="inline-flex rounded-md border p-1">
      <button type="button" aria-label="List view" aria-pressed={layout === 'list'} className={`rounded p-2 focus-visible:ring-2 focus-visible:ring-ring ${layout === 'list' ? 'bg-muted text-foreground' : 'text-muted-foreground'}`} onClick={() => setLayout('list')}><List aria-hidden="true" className="h-4 w-4" /></button>
      <button type="button" aria-label="Grid view" aria-pressed={layout === 'grid'} className={`rounded p-2 focus-visible:ring-2 focus-visible:ring-ring ${layout === 'grid' ? 'bg-muted text-foreground' : 'text-muted-foreground'}`} onClick={() => setLayout('grid')}><LayoutGrid aria-hidden="true" className="h-4 w-4" /></button>
    </div>
    </div>
    {filter && <button type="button" className="self-start rounded border px-3 py-2 text-sm" onClick={() => setFilter('')}>Clear filter</button>}
    {hasMore && <p className="text-xs text-muted-foreground">More references are available on later pages. Filtering and sorting apply only to this page.</p>}
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm text-destructive">{error}</p>}
    {loading ? <p role="status" className="py-8 text-center text-sm">Loading authorized file inventory…</p>
      : visible.length === 0 ? <div role="status" className="space-y-2 py-8 text-center text-sm text-muted-foreground">
        <p className="font-medium text-foreground">{filter ? 'No matching references on this page.' : 'No files or folders in this view.'}</p>
        <p>{filter ? 'Clear the filter to see other references on this page.' : 'No references were supplied for this location on the current page.'}</p>
      </div>
      : <ul className={layout === 'grid' ? 'grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-3' : 'flex min-w-0 flex-col gap-1'} aria-label="Files and folders">
        {visible.map((item) => <li key={item.source_id} className={`flex min-w-0 items-center gap-3 rounded-lg border p-3 ${selectionSet.has(item.source_id) ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'}`}>
          <input type={multiSelect ? 'checkbox' : 'radio'} name="file-explorer-selection"
            aria-label={'Select ' + item.name} checked={selectionSet.has(item.source_id)} disabled={loading || Boolean(error) || (atLimit && !selectionSet.has(item.source_id))}
            className="h-4 w-4 shrink-0 accent-primary focus-visible:ring-2 focus-visible:ring-ring" onChange={() => select(item)} />
          {item.kind === 'folder' ? <Folder aria-hidden="true" className="h-5 w-5 shrink-0 text-muted-foreground" /> : <FileText aria-hidden="true" className="h-5 w-5 shrink-0 text-muted-foreground" />}
          {item.kind === 'folder'
            ? <button type="button" className="min-w-0 flex-1 truncate text-left text-sm font-medium underline"
                onClick={() => { setParentId(item.source_id); setFilter(''); }} aria-label={'Open folder ' + item.name}>
                {item.name}</button>
            : <div className="min-w-0 flex-1">
                <p className="truncate text-sm" title={item.name}>{item.name}</p>
                <p className="text-xs text-muted-foreground">{prettyBytes(item.size_bytes)}</p>
              </div>}
        </li>)}
      </ul>}
    <footer className="flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-xs text-muted-foreground">
      <div className="space-y-1">
        <p role="status" aria-live="polite">{selectionSet.size} selected · {visible.length} shown on this page · Maximum {selectionLimit} selections{atLimit ? ' · Selection limit reached. Deselect a reference to select another.' : ''}</p>
        <p>Refreshing or moving to the next page clears this selection.</p>
      </div>
      {selectionSet.size > 0 && <button type="button" className="rounded border px-3 py-2 text-sm" onClick={clearSelections} disabled={loading}>Clear selection</button>}
      {hasMore && <button type="button" className="rounded border px-3 py-2 text-sm"
        disabled={loading || Boolean(error) || !pageEvidenceValid} onClick={nextPage}>Next page</button>}
    </footer>
  </section>;
}

export function SharedFileExplorer(props: FileExplorerProps) {
  // A new host-issued page identity resets local folder/filter/selection state.
  // Authorization and stale-response rejection remain host responsibilities.
  return <FileExplorerView key={props.pageKey ?? 'initial'} {...props} />;
}

export default function FileExplorerPage(props: FileExplorerProps) {
  return <SharedFileExplorer {...props} />;
}
