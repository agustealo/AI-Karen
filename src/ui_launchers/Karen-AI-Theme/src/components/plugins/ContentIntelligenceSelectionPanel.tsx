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
        term.term.length > 128 ||
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

export function ContentIntelligenceSelectionPanel({
  sources,
}: {
  sources: AnalyzableSource[];
}) {
  const [status, setStatus] = useState<'idle' | 'pending' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<AnalyzedResponse | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => {
    generation.current += 1;
    controller.current?.abort();
  }, []);

  async function analyze(): Promise<void> {
    if (status === 'pending' || sources.length < 1 || sources.length > 12) {
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
        { operation: 'analyze', references: sources.map((ref) => ({
          source_id: ref.source_id, revision: ref.revision,
        })) },
        { signal: signal.signal },
      );
      if (signal.signal.aborted || generation.current !== execution) return;
      setResult(validateAnalysis(response, sources));
      setStatus('success');
    } catch {
      if (signal.signal.aborted || generation.current !== execution) return;
      setResult(null);
      setStatus('error');
    }
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
      <button
        type="button"
        className="rounded border px-3 py-2 text-sm disabled:opacity-50"
        disabled={status === 'pending' || sources.length < 1 || sources.length > 12}
        onClick={() => { void analyze(); }}
      >
        {status === 'pending' ? 'Analyzing authorized files…' : 'Analyze selected files'}
      </button>
      {sources.length > 12 && (
        <p role="status" className="text-xs text-muted-foreground">
          Select at most 12 files for analysis.
        </p>
      )}
      {status === 'pending' && <p role="status">Checking current access and analyzing…</p>}
      {status === 'error' && (
        <p role="alert">Analysis is unavailable or access was denied. Refresh the file inventory and retry.</p>
      )}
      {status === 'success' && result && (
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
                    ? doc.top_terms.map((term) => `${term.term} (${term.count})`).join(', ')
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
