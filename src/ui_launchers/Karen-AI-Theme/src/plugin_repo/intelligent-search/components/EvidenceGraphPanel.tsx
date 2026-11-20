import React, { useState } from 'react';
import { ExternalLink, GitBranch, ShieldCheck } from 'lucide-react';
import { SearchEvidenceGraph } from '../types';

interface EvidenceGraphPanelProps {
  graph: SearchEvidenceGraph | undefined;
}

/**
 * Read-only, keyboard-accessible provenance explorer.
 *
 * No browser-derived edges, entity inference, graph persistence, or
 * authorization decisions. All links derive from the canonical search result.
 */
export function EvidenceGraphPanel({ graph }: EvidenceGraphPanelProps) {
  const [selected, setSelected] = useState<string | null>(null);

  if (!graph) {
    return (
      <section role="status" className="rounded-2xl border border-border/60 p-5">
        <h3 className="text-lg font-semibold">Evidence relationships unavailable</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          This result has no server-authored evidence graph. Retrieved sources remain available
          in the Sources section.
        </p>
      </section>
    );
  }

  const nodes = graph.nodes ?? [];
  const edges = graph.edges ?? [];
  const selectedNode = nodes.find((node) => node.id === selected);
  const linked = selectedNode
    ? edges.filter((edge) => edge.from === selectedNode.id || edge.to === selectedNode.id)
    : [];

  return (
    <section aria-label="Evidence relationship explorer" className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <GitBranch className="h-5 w-5 text-primary" aria-hidden="true" />
        <div>
          <h3 className="text-lg font-semibold">Evidence relationships</h3>
          <p className="text-sm text-muted-foreground">
            Source-backed passage links only. No inferred entities or claims.
          </p>
        </div>
      </div>

      {graph.truncated && (
        <p role="status" className="rounded-xl border border-border/60 p-3 text-sm">
          This graph is limited to a bounded subset of sources and passages.
        </p>
      )}

      {nodes.length === 0 ? (
        <p role="status" className="rounded-xl border border-border/60 p-4 text-sm">
          No verified evidence relationships are available for this search.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.7fr)]">
          <div className="space-y-3">
            <p className="text-sm font-medium">
              {nodes.length} nodes · {edges.length} source relationships
            </p>
            <ul className="space-y-2" aria-label="Evidence nodes">
              {nodes.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    aria-pressed={selected === node.id}
                    onClick={() => setSelected(node.id)}
                    className={`flex min-h-11 w-full flex-col items-start rounded-xl border px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                      selected === node.id
                        ? 'border-primary bg-primary/10'
                        : 'border-border/60 hover:bg-muted/40'
                    }`}
                  >
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {node.kind} · {node.evidence_level === 'fetched_page' ? 'Fetched' : 'Discovery only'}
                    </span>
                    <span className="mt-1 break-words text-sm font-semibold">{node.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <aside aria-label="Selected evidence details" className="rounded-2xl border border-border/60 p-4">
            {selectedNode ? (
              <div className="space-y-3">
                <h4 className="break-words font-semibold">{selectedNode.label}</h4>
                <p className="text-sm text-muted-foreground">
                  {selectedNode.kind === 'passage'
                    ? 'A passage associated with a fetched source.'
                    : selectedNode.evidence_level === 'fetched_page'
                      ? 'Source content was fetched during retrieval.'
                      : 'Discovery result only. The linked page was not verified as fetched.'}
                </p>
                {selectedNode.evidence_level === 'fetched_page' && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                    Fetched-page provenance
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  {linked.length} directly recorded source relationships
                </p>
                {linked.map((edge) => (
                  <p key={edge.id} className="rounded-lg bg-muted/40 px-3 py-2 text-xs">
                    {edge.type.replace('_', ' ')} · source URL matched
                  </p>
                ))}
                {/^https?:\/\//.test(selectedNode.url) && (
                  <a
                    className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
                    href={selectedNode.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open source <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  </a>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a source or passage to inspect its provenance.
              </p>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}
