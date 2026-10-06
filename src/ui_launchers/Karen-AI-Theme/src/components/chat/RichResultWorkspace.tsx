'use client';

import {
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
  return /^(https?:\/\/)/i.test(href) || href.startsWith('/') ? href : null;
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
          <div>
            <p className="karen-panel-label text-foreground/90">Workspace</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Files, artifacts, structured output, and evidence from this turn.
            </p>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3.5">
        {artifacts.length > 0 && (
          <section className="karen-surface rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-primary" />
              <span className="karen-panel-label">Artifacts</span>
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

        {Object.keys(structured).length > 0 && (
          <section className="karen-surface rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Braces className="h-3.5 w-3.5 text-accent" />
              <span className="karen-panel-label">Structured result</span>
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

        {attachments.length > 0 && (
          <section className="karen-surface rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Paperclip className="h-3.5 w-3.5 text-primary" />
              <span className="karen-panel-label">Attachments</span>
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

        {references.length > 0 && (
          <section className="karen-surface rounded-xl p-3">
            <div className="mb-2 flex items-center gap-2">
              <Link2 className="h-3.5 w-3.5 text-accent" />
              <span className="karen-panel-label">Evidence</span>
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
