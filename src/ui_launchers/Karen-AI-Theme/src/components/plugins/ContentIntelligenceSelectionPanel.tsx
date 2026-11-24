'use client';

/**
 * Host-owned presentation bridge from File Explorer references to the
 * Content Intelligence authenticated source endpoint.
 *
 * No storage credentials, file bytes, filesystem paths, permission decisions
 * or fake analysis results are created here. The backend authorizes every read.
 */
import { useEffect, useRef, useState } from 'react';

import { apiClient } from '@/lib/api';

export interface AnalyzableSource {
  source_id: string;
  revision: string;
}

interface AnalyzedDocument {
  id: string;
  name: string;
  sha256: string;
  characters: number;
  top_terms: Array<{ term: string; count: number }>;
}

interface AnalyzedResponse {
  operation: 'analyze';
  persisted: false;
  documents: AnalyzedDocument[];
}

function validateAnalysis(raw: unknown, selected: AnalyzableSource[]): AnalyzedResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('Invalid analysis response');
  }
  const result = raw as Record<string, unknown>;
  if (
    result.operation !== 'analyze' ||
    result.persisted !== false ||
    !Array.isArray(result.documents) ||
    result.documents.length !== selected.length
  ) {
    throw new Error('Invalid analysis response');
  }

  const allowed = new Map(selected.map((source) => [source.source_id, source.revision]));
  const seen = new Set<string>();
  const documents: AnalyzedDocument[] = [];
  for (const value of result.documents) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error('Invalid analysis response');
    }
    const doc = value as Record<string, unknown>;
    if (
      typeof doc.id !== 'string' ||
      !allowed.has(doc.id) ||
      seen.has(doc.id) ||
      typeof doc.sha256 !== 'string' ||
      allowed.get(doc.id) !== doc.sha256 ||
      typeof doc.name !== 'string' ||
      doc.name.length < 1 ||
      doc.name.length > 256 ||
      typeof doc.characters !== 'number' ||
      !Number.isSafeInteger(doc.characters) ||
      doc.characters < 1 ||
      doc.characters > 100_000 ||
      !Array.isArray(doc.top_terms) ||
      doc.top_terms.length > 12
    ) {
      throw new Error('Invalid analysis response');
    }

    const terms: Array<{ term: string; count: number }> = [];
    for (const item of doc.top_terms) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) {
        throw new Error('Invalid analysis response');
      }
      const term = item as Record<string, unknown>;
      if (
        typeof term.term !== 'string' ||
        !term.term ||
        // Canonical lexical terms may exceed 128 chars; bound presentation instead.
        typeof term.count !== 'number' ||
        !Number.isSafeInteger(term.count) ||
        term.count <= 0
      ) {
        throw new Error('Invalid analysis response');
      }
      terms.push({ term: term.term, count: term.count });
    }
    seen.add(doc.id);
    documents.push({
      id: doc.id,
      sha256: doc.sha256,
      name: doc.name,
      characters: doc.characters,
      top_terms: terms,
    });
  }
  return { operation: 'analyze', persisted: false, documents };
}

interface SearchMatch {
  document_id: string;
  document_name: string;
  offset: number;
  end_offset: number;
  excerpt: string;
  score: number;
}

interface SearchResponse {
  operation: 'search';
  persisted: false;
  matches: SearchMatch[];
}

function validateSearch(raw: unknown, selected: AnalyzableSource[], query: string): SearchResponse {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('Invalid search response');
  }
  const result = raw as Record<string, unknown>;
  if (result.operation !== 'search' || result.persisted !== false ||
      result.query !== query || result.search_semantics !== 'lexical_evidence_only' ||
      !Array.isArray(result.matches) || result.matches.length > 12) {
    throw new Error('Invalid search response');
  }
  const allowed = new Map(selected.map((source) => [source.source_id, source.revision]));
  const matches: SearchMatch[] = [];
  for (const value of result.matches) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error('Invalid search response');
    }
    const hit = value as Record<string, unknown>;
    if (typeof hit.document_id !== 'string' || !allowed.has(hit.document_id) ||
        hit.sha256 !== allowed.get(hit.document_id) ||
        typeof hit.document_name !== 'string' || !hit.document_name || hit.document_name.length > 256 ||
        hit.folder_id !== null ||
        typeof hit.offset !== 'number' || !Number.isSafeInteger(hit.offset) || hit.offset < 0 ||
        typeof hit.end_offset !== 'number' || !Number.isSafeInteger(hit.end_offset) ||
        hit.end_offset <= hit.offset || hit.end_offset > 100_000 ||
        typeof hit.excerpt !== 'string' || Array.from(hit.excerpt).length !== hit.end_offset - hit.offset ||
        Array.from(hit.excerpt).length > 600 ||
        typeof hit.score !== 'number' || !Number.isFinite(hit.score) || hit.score <= 0 || hit.score > 1) {
      throw new Error('Invalid search response');
    }
    matches.push({
      document_id: hit.document_id, document_name: hit.document_name,
      offset: hit.offset, end_offset: hit.end_offset, excerpt: hit.excerpt, score: hit.score,
    });
  }
  return { operation: 'search', persisted: false, matches };
}

export function ContentIntelligenceSelectionPanel({
  sources,
  onRefreshInventory,
}: {
  sources: AnalyzableSource[];
  onRefreshInventory?: () => void;
}) {
  const [status, setStatus] = useState<'idle' | 'pending' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<AnalyzedResponse | SearchResponse | null>(null);
  const [operation, setOperation] = useState<'analyze' | 'search'>('analyze');
  const [query, setQuery] = useState('');
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => {
    generation.current += 1;
    controller.current?.abort();
  }, []);

  async function analyze(): Promise<void> {
    const searchQuery = query.trim();
    if (status === 'pending' || sources.length < 1 || sources.length > 12 ||
        (operation === 'search' && (!searchQuery || searchQuery.length > 512))) {
      return;
    }
    controller.current?.abort();
    const signal = new AbortController();
    controller.current = signal;
    const execution = ++generation.current;
    setResult(null);
    setStatus('pending');
    try {
      const response = await apiClient.post<unknown>(
        '/api/plugins/content-intelligence/owner-sources',
        { operation, references: sources.map((ref) => ({
          source_id: ref.source_id, revision: ref.revision,
        })), ...(operation === 'search' ? { query: searchQuery } : {}) },
        { signal: signal.signal },
      );
      if (signal.signal.aborted || generation.current !== execution) return;
      setResult(operation === 'search'
        ? validateSearch(response, sources, searchQuery)
        : validateAnalysis(response, sources));
      setStatus('success');
    } catch {
      if (signal.signal.aborted || generation.current !== execution) return;
      setResult(null);
      setStatus('error');
    }
  }

  function resetResult(): void {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    setResult(null);
    setStatus('idle');
  }

  function refreshInventory(): void {
    // Revoke this presentation attempt before asking the authenticated host
    // for fresh metadata. The selection cannot be reused as an access grant.
    resetResult();
    onRefreshInventory?.();
  }

  return (
    <section className="mt-4 space-y-3 rounded-lg border p-4" aria-label="Content Intelligence analysis">
      <div>
        <h3 className="text-sm font-semibold">Content Intelligence</h3>
        <p className="text-xs text-muted-foreground">
          Analyze selected, supported text or code artifacts. Current source permissions and revisions
          are checked by Karen before content is read. No persistent index is created.
        </p>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        Operation
        <select className="rounded border bg-background p-2" value={operation}
          onChange={(event) => { resetResult(); setOperation(event.target.value === 'search' ? 'search' : 'analyze'); }}>
          <option value="analyze">Analyze</option>
          <option value="search">Search documents</option>
        </select>
      </label>
      {operation === 'search' && <label className="flex flex-col gap-1 text-sm">
        Search terms
        <input className="rounded border bg-background p-2" value={query} maxLength={512}
          onChange={(event) => { resetResult(); setQuery(event.target.value); }} />
      </label>}
      <button
        type="button"
        className="rounded border px-3 py-2 text-sm disabled:opacity-50"
        disabled={status === 'pending' || sources.length < 1 || sources.length > 12 ||
          (operation === 'search' && !query.trim())}
        onClick={() => { void analyze(); }}
      >
        {operation === 'search' ? (status === 'pending' ? 'Searching authorized files…' : 'Search selected files')
          : (status === 'pending' ? 'Analyzing authorized files…' : 'Analyze selected files')}
      </button>
      {sources.length > 12 && (
        <p role="status" className="text-xs text-muted-foreground">
          Select at most 12 files for analysis.
        </p>
      )}
      {status === 'pending' && <p role="status">Checking current access and analyzing…</p>}
      {status === 'error' && (
        <div className="space-y-2">
          <p role="alert">Analysis is unavailable or access was denied. The selected file may have changed. Refresh inventory and reselect before retrying.</p>
          {onRefreshInventory && (
            <button
              type="button"
              className="rounded border px-3 py-2 text-sm"
              onClick={refreshInventory}
            >
              Refresh inventory and reselect
            </button>
          )}
        </div>
      )}
      {status === 'success' && result?.operation === 'search' && (
        <div role="status" aria-label="Verified search results" className="space-y-2">
          <p className="text-xs text-muted-foreground">Lexical matches only. No content was saved by this operation.</p>
          {result.matches.length === 0 ? <p>No matching passages found.</p> : (
            <ul className="space-y-2">
              {result.matches.map((hit, index) => (
                <li key={hit.document_id + ':' + hit.offset + ':' + index} className="rounded border p-3 text-sm break-words">
                  <p className="font-medium">{hit.document_name}</p>
                  <p className="whitespace-pre-wrap">{hit.excerpt}</p>
                  <p className="text-xs text-muted-foreground">Characters {hit.offset}–{hit.end_offset} · {Math.round(hit.score * 100)}% query term coverage</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {status === 'success' && result?.operation === 'analyze' && (
        <div role="status" className="space-y-3" aria-label="Verified analysis results">
          <p className="text-xs text-muted-foreground">
            Lexical analysis of {result.documents.length} authorized file(s). No content was saved by this operation.
          </p>
          <ul className="space-y-2">
            {result.documents.map((doc) => (
              <li key={doc.id} className="rounded border p-3 text-sm">
                <p className="font-medium break-words">{doc.name}</p>
                <p className="text-xs text-muted-foreground">{doc.characters} characters</p>
                <p className="mt-2 text-xs break-words">
                  {doc.top_terms.length
                    ? doc.top_terms.map((term) => `${term.term.length > 128 ? term.term.slice(0, 128) + '…' : term.term} (${term.count})`).join(', ')
                    : 'No recurring terms identified.'}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
