'use client';

import { useEffect, useState } from 'react';
import type { DragEvent } from 'react';
import {
  Settings2,
  Braces,
  ExternalLink,
  FileText,
  FolderKanban,
  Link2,
  Paperclip,
} from 'lucide-react';

import type {
  ChatArtifact,
  ChatAttachment,
  ChatMessage,
  Citation,
} from '@/lib/types';

type WorkspaceCard = 'artifacts' | 'structured' | 'attachments' | 'evidence';
const DEFAULT_ORDER: WorkspaceCard[] = ['artifacts', 'structured', 'attachments', 'evidence'];
const LABELS: Record<WorkspaceCard, string> = {
  artifacts: 'Artifacts', structured: 'Structured output',
  attachments: 'Files & attachments', evidence: 'Evidence',
};
const STORAGE_KEY = 'karen.workspace.cards.v1';
function isWorkspaceCard(value: unknown): value is WorkspaceCard {
  return typeof value === 'string' && DEFAULT_ORDER.includes(value as WorkspaceCard);
}
function readLayout(): { order: WorkspaceCard[]; hidden: WorkspaceCard[] } {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
    const order = Array.isArray(saved.order) ? saved.order.filter(isWorkspaceCard) : [];
    const hidden = Array.isArray(saved.hidden) ? saved.hidden.filter(isWorkspaceCard) : [];
    return { order: [...new Set([...order, ...DEFAULT_ORDER])], hidden: [...new Set(hidden)] };
  } catch {
    return { order: [...DEFAULT_ORDER], hidden: [] };
  }
}

interface RichResultWorkspaceProps {
  message?: ChatMessage;
}

const nonEmptyObject = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) &&
  typeof value === 'object' &&
  !Array.isArray(value) &&
  Object.keys(value as Record<string, unknown>).length > 0;

const asDisplayName = (
  item: ChatArtifact | ChatAttachment,
  fallback: string,
): string => {
  const record = item as Record<string, unknown>;
  return (
    String(
      record.title ||
        record.name ||
        record.filename ||
        fallback,
    ).trim() || fallback
  );
};

const asHref = (value: unknown): string | null => {
  if (typeof value !== 'string' || !value.trim()) return null;
  const href = value.trim();
  return /^(https?:\/\/)/i.test(href) ||
    (href.startsWith('/') && !href.startsWith('//'))
    ? href
    : null;
};

const DataValue = ({ value }: { value: unknown }) => {
  if (typeof value === 'string') {
    return (
      <p className="whitespace-pre-wrap text-xs leading-6 text-foreground/90">
        {value}
      </p>
    );
  }

  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-border/60 bg-background/55 p-3 font-mono text-[10px] leading-5 text-foreground/80">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
};

const LinkRow = ({ citation }: { citation: Citation }) => {
  const href = asHref(citation.url);
  const body = (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-xs font-semibold text-foreground">
          {citation.title || citation.url}
        </p>
        {citation.snippet && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-muted-foreground">
            {citation.snippet}
          </p>
        )}
      </div>
      {href && (
        <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
      )}
    </div>
  );

  if (!href) {
    return (
      <div className="rounded-lg border border-border/60 bg-background/30 p-3">
        {body}
      </div>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="group block rounded-lg border border-border/60 bg-background/30 p-3 transition-colors hover:border-primary/25 hover:bg-muted/50"
    >
      {body}
    </a>
  );
};

export default function RichResultWorkspace({
  message,
}: RichResultWorkspaceProps) {
  const [order, setOrder] = useState<WorkspaceCard[]>(DEFAULT_ORDER);
  const [hidden, setHidden] = useState<WorkspaceCard[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dragged, setDragged] = useState<WorkspaceCard | null>(null);
  useEffect(() => {
    const saved = readLayout();
    setOrder(saved.order);
    setHidden(saved.hidden);
  }, []);
  const saveLayout = (nextOrder: WorkspaceCard[], nextHidden: WorkspaceCard[]) => {
    setOrder(nextOrder);
    setHidden(nextHidden);
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ order: nextOrder, hidden: nextHidden })); }
    catch { /* Browser storage may be unavailable: current-session layout still works. */ }
  };
  const move = (source: WorkspaceCard, destination: WorkspaceCard) => {
    if (source === destination) return;
    const next = order.filter((card) => card !== source);
    next.splice(next.indexOf(destination), 0, source);
    saveLayout(next, hidden);
  };
  const shift = (card: WorkspaceCard, direction: -1 | 1) => {
    const from = order.indexOf(card);
    const to = from + direction;
    if (to < 0 || to >= order.length) return;
    const next = [...order];
    [next[from], next[to]] = [next[to], next[from]];
    saveLayout(next, hidden);
  };
  const cardProps = (card: WorkspaceCard) => ({
    draggable: true,
    onDragStart: () => setDragged(card),
    onDragEnd: () => setDragged(null),
    onDragOver: (event: DragEvent<HTMLElement>) => event.preventDefault(),
    onDrop: (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      if (dragged) move(dragged, card);
      setDragged(null);
    },
    style: { order: order.indexOf(card) },
    'aria-label': `${LABELS[card]} card, draggable`,
  });
  if (!message) return null;

  const structured = nonEmptyObject(message.structuredContent)
    ? message.structuredContent
    : {};
  const artifacts = Array.isArray(message.artifacts) ? message.artifacts : [];
  const attachments = Array.isArray(message.attachments)
    ? message.attachments
    : [];
  const sources = Array.isArray(message.sources) ? message.sources : [];
  const citations = Array.isArray(message.citations) ? message.citations : [];
  const references = sources.length > 0 ? sources : citations;

  const hasContent =
    Object.keys(structured).length > 0 ||
    artifacts.length > 0 ||
    attachments.length > 0 ||
    references.length > 0;

  if (!hasContent) return null;

  return (
    <aside
      className="hidden w-[22rem] shrink-0 border-l border-border/70 bg-background/40 2xl:flex 2xl:flex-col"
      aria-label="Result workspace"
      data-testid="rich-result-workspace"
    >
      <div className="border-b border-border/70 px-4 py-3">
        <div className="flex items-center gap-2">
          <FolderKanban className="h-4 w-4 text-primary" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">Workspace</h2>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Files, artifacts, structured output, and evidence from this turn.
            </p>
          </div>
          <button type="button" aria-label="Customize workspace cards" aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="rounded-md p-2 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
            <Settings2 className="h-4 w-4" />
          </button>
        </div>
        {settingsOpen && <div className="mt-3 space-y-2" aria-label="Workspace card preferences">
          <p className="text-xs text-muted-foreground">Choose cards and drag to reorder. Preferences are local to this browser.</p>
          {order.map((card) => <div key={card} className="flex items-center gap-2 text-xs">
            <label className="flex min-w-0 flex-1 items-center gap-2">
              <input type="checkbox" checked={!hidden.includes(card)}
                onChange={(e) => saveLayout(order, e.target.checked ? hidden.filter((v) => v !== card) : [...hidden, card])} />
              {LABELS[card]}
            </label>
            <button type="button" aria-label={`Move ${LABELS[card]} up`} disabled={order.indexOf(card) === 0}
              onClick={() => shift(card, -1)}
              className="rounded border px-2 py-1 disabled:opacity-30">↑</button>
            <button type="button" aria-label={`Move ${LABELS[card]} down`} disabled={order.indexOf(card) === order.length - 1}
              onClick={() => shift(card, 1)}
              className="rounded border px-2 py-1 disabled:opacity-30">↓</button>
          </div>)}
        </div>}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-3.5">
        {artifacts.length > 0 && !hidden.includes('artifacts') && (
          <section {...cardProps('artifacts')} className="karen-surface shrink-0 rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-primary" />
              <span className="text-sm font-semibold tracking-tight">Artifacts</span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {artifacts.length}
              </span>
            </div>
            <div className="space-y-2">
              {artifacts.map((artifact, index) => {
                const href = asHref(artifact.url);
                return (
                  <div
                    key={String(artifact.id || artifact.path || index)}
                    className="rounded-lg border border-border/60 bg-background/30 p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold">
                          {asDisplayName(artifact, `Artifact ${index + 1}`)}
                        </p>
                        <p className="mt-1 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                          {String(artifact.type || artifact.kind || 'artifact')}
                        </p>
                      </div>
                      {href && (
                        <a
                          href={href}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-primary"
                          aria-label="Open artifact"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                    {artifact.content !== undefined && (
                      <div className="mt-3">
                        <DataValue value={artifact.content} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {Object.keys(structured).length > 0 && !hidden.includes('structured') && (
          <section {...cardProps('structured')} className="karen-surface shrink-0 rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Braces className="h-3.5 w-3.5 text-accent" />
              <span className="text-sm font-semibold tracking-tight">Structured result</span>
            </div>
            <div className="space-y-2">
              {Object.entries(structured).map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-lg border border-border/60 bg-background/30 p-3"
                >
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {key.replace(/_/g, ' ')}
                  </p>
                  <DataValue value={value} />
                </div>
              ))}
            </div>
          </section>
        )}

        {attachments.length > 0 && !hidden.includes('attachments') && (
          <section {...cardProps('attachments')} className="karen-surface shrink-0 rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Paperclip className="h-3.5 w-3.5 text-primary" />
              <span className="text-sm font-semibold tracking-tight">Attachments</span>
            </div>
            <div className="space-y-2">
              {attachments.map((attachment, index) => {
                const href = asHref(attachment.url);
                return (
                  <div
                    key={String(attachment.id || attachment.path || index)}
                    className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/30 p-2.5"
                  >
                    <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">
                        {asDisplayName(attachment, `Attachment ${index + 1}`)}
                      </p>
                      <p className="font-mono text-[9px] text-muted-foreground">
                        {String(
                          attachment.media_type ||
                            attachment.mime_type ||
                            'file',
                        )}
                      </p>
                    </div>
                    {href && (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-primary"
                        aria-label="Open attachment"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {references.length > 0 && !hidden.includes('evidence') && (
          <section {...cardProps('evidence')} className="karen-surface shrink-0 rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Link2 className="h-3.5 w-3.5 text-accent" />
              <span className="text-sm font-semibold tracking-tight">Evidence</span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {references.length}
              </span>
            </div>
            <div className="space-y-2">
              {references.map((citation) => (
                <LinkRow key={citation.id || citation.url} citation={citation} />
              ))}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}
