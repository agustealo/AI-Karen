import React, { useMemo, useState } from 'react';
import { IntelligentSearchResponse, SearchResultItem, SearchSourceItem } from '../types';
import { Send, FileText, Code, AlignLeft, Download, ExternalLink } from 'lucide-react';

interface PanelProps {
  response: IntelligentSearchResponse;
}

type ViewMode = 'snippet' | 'markdown' | 'json';

/**
 * Enhanced function to send rich content to the main Karen chat
 */
const sendToChat = (item: any) => {
  let content = `I found this information for you:\n\n**${item.title || 'Search Result'}**\n\n`;
  
  if (item.extracted_data || item.extractedData) {
    const data = item.extracted_data || item.extractedData;
    content += `### Structured Data\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\`\n\n`;
  }
  
  if (item.markdown || item.full_content) {
    const fullText = item.markdown || item.full_content;
    content += `### Content\n${fullText}\n\n`;
  } else if (item.content || item.snippet) {
    content += `${item.content || item.snippet}\n\n`;
  } else {
    content += '_No preview content was available for this item._\n\n';
  }
  
  if (item.url) {
    content += `Source: ${item.url}`;
  }
  
  const event = new CustomEvent('karen:inject-message', { 
    detail: { 
      content,
      role: 'user',
      autoSubmit: true 
    } 
  });
  window.dispatchEvent(event);
};

/**
 * Helper to toggle between different content views
 */
function ViewToggle({ active, onClick, label, icon }: { active: boolean; onClick: () => void; label: string; icon: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all px-3 py-1.5 rounded-lg ${
        active ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:text-foreground'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

export function ResultsPanel({ response }: PanelProps) {
  const results = response.results || [];
  const sources = response.sources || [];
  const initialActiveSourceIndex = useMemo(() => getMostRelevantSourceIndex(sources), [sources]);
  const [activeSourceIndex, setActiveSourceIndex] = useState(initialActiveSourceIndex);
  const [sourceViewMode, setSourceViewMode] = useState<ViewMode>('snippet');

  const featuredSource = useMemo(
    () => sources[Math.min(activeSourceIndex, Math.max(0, sources.length - 1))],
    [activeSourceIndex, sources],
  );

  const sourceCount = response.diagnostics?.sourceCount ?? sources.length ?? 0;
  const resultCount = results.length;
  const providerLabel = response.provider || response.metadata?.provider || 'crawl4ai';

  React.useEffect(() => {
    setActiveSourceIndex(initialActiveSourceIndex);
  }, [initialActiveSourceIndex, sources]);

  return (
    <div className="space-y-6">
      {/* 1. Summary & Overview Section */}
      <div className="rounded-3xl border border-border/60 bg-card/90 p-6 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/40 pb-5">
          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground font-bold">Intelligent Summary</p>
            <h3 className="text-xl font-semibold text-foreground">Synthesis of {sourceCount} sources</h3>
          </div>
          <button 
            onClick={() => sendToChat({ title: 'Search Summary', snippet: response.summary, url: 'Live Search Intelligence' })}
            className="flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-xs font-bold uppercase tracking-wider text-primary-foreground transition-all hover:scale-105 shadow-lg active:scale-95"
          >
            <Send className="h-3.5 w-3.5" />
            Inject Summary
          </button>
        </div>

        <div className="mt-5 grid gap-6 lg:grid-cols-[1fr_300px]">
          <div className="space-y-4">
            <div className="rounded-2xl border border-border/60 bg-background/50 p-5 text-sm leading-7 text-muted-foreground backdrop-blur-sm">
              {response.summary || <span className="italic">Karen was unable to generate a summary for this crawl.</span>}
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <MetricPill label="Provider" value={providerLabel} />
              <MetricPill label="Sources" value={sourceCount} />
              <MetricPill label="Passages" value={resultCount} />
              <MetricPill label="Time" value={`${response.execution_time_ms || 0}ms`} />
            </div>
          </div>

          <div className="rounded-2xl border border-border/60 bg-background/70 p-4 flex flex-col justify-center text-center space-y-3">
             <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                <FileText className="h-6 w-6 text-primary" />
             </div>
             <div>
               <p className="text-sm font-semibold text-foreground">Structured Output</p>
               <p className="text-[11px] text-muted-foreground mt-1">Crawl4AI identified {results.length} key passages from the live web.</p>
             </div>
          </div>
        </div>
      </div>

      {/* 2. Intelligence Explorer Section (Merged sources/excerpts) */}
      {sources.length > 0 && (
        <div className="rounded-3xl border border-border/60 bg-card/90 overflow-hidden shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
          <div className="bg-muted/30 px-6 py-4 border-b border-border/60 flex items-center justify-between">
             <div className="flex items-center gap-2">
               <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
               <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground font-bold">Source Intelligence</p>
             </div>
             <span className="text-[10px] bg-background/80 border border-border/60 px-2 py-0.5 rounded-full text-muted-foreground">
               {activeSourceIndex + 1} / {sources.length}
             </span>
          </div>

          <div className="grid gap-0 xl:grid-cols-[320px_1fr]">
            <div className="border-r border-border/60 bg-muted/10">
              <div className="max-h-[32rem] space-y-1 overflow-auto p-3 custom-scrollbar">
                {sources.map((source, index) => {
                  const isActive = index === activeSourceIndex;
                  return (
                    <button
                      key={source.id || `${source.url}-${index}`}
                      type="button"
                      onClick={() => setActiveSourceIndex(index)}
                      className={`w-full rounded-xl border px-3 py-3 text-left transition-all ${
                        isActive
                          ? 'border-primary/50 bg-primary/10 shadow-sm'
                          : 'border-transparent hover:bg-muted/50'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`h-5 w-5 shrink-0 flex items-center justify-center rounded-full text-[10px] font-bold ${isActive ? 'bg-primary text-primary-foreground' : 'bg-muted-foreground/20 text-muted-foreground'}`}>
                          {index + 1}
                        </span>
                        <span className={`truncate text-[11px] font-bold uppercase tracking-wider ${isActive ? 'text-primary' : 'text-muted-foreground'}`}>
                          {source.domain || domainFromUrl(source.url)}
                        </span>
                      </div>
                      <div className={`truncate text-sm font-medium ${isActive ? 'text-foreground' : 'text-muted-foreground/80'}`}>
                        {source.title || source.url}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex flex-col bg-background/40">
              <div className="flex items-center justify-between border-b border-border/60 bg-muted/20 px-5 py-3">
                <div className="flex gap-4">
                  <ViewToggle active={sourceViewMode === 'snippet'} onClick={() => setSourceViewMode('snippet')} label="Snippet" icon={<AlignLeft className="h-3 w-3" />} />
                  <ViewToggle active={sourceViewMode === 'markdown'} onClick={() => setSourceViewMode('markdown')} label="Markdown" icon={<FileText className="h-3 w-3" />} />
                  <ViewToggle active={sourceViewMode === 'json'} onClick={() => setSourceViewMode('json')} label="JSON" icon={<Code className="h-3 w-3" />} />
                </div>
                {featuredSource?.publishedDate && (
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest">{featuredSource.publishedDate}</span>
                )}
              </div>
              
              <div className="p-6 flex-1 overflow-auto max-h-[28rem] custom-scrollbar min-h-[16rem]">
                <h3 className="text-xl font-semibold mb-4 text-foreground leading-tight">
                  {featuredSource?.title || 'Source Preview'}
                </h3>
                
                {sourceViewMode === 'snippet' && (
                  <p className="whitespace-pre-wrap break-words text-sm leading-8 text-muted-foreground/90">
                    {featuredSource?.content || featuredSource?.snippet || 'No content preview available.'}
                  </p>
                )}
                {sourceViewMode === 'markdown' && (
                  <pre className="whitespace-pre-wrap break-words text-xs leading-6 text-foreground/90 font-mono bg-muted/10 p-4 rounded-xl border border-border/40">
                    {featuredSource?.markdown || featuredSource?.full_content || 'Markdown content not available for this source.'}
                  </pre>
                )}
                {sourceViewMode === 'json' && (
                  <pre className="text-[11px] leading-5 text-foreground/80 font-mono bg-muted/10 p-4 rounded-xl border border-border/40">
                    {JSON.stringify(featuredSource, null, 2)}
                  </pre>
                )}
              </div>

              {featuredSource?.url && (
                <div className="p-5 pt-0 mt-auto flex flex-wrap gap-3">
                  <a
                    href={featuredSource.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-full bg-primary/10 border border-primary/20 px-4 py-2 text-xs font-bold text-primary transition-all hover:bg-primary/20 shadow-sm"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Visit Original
                  </a>
                  <button
                    type="button"
                    onClick={() => sendToChat(featuredSource)}
                    className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-4 py-2 text-xs font-bold text-foreground transition-all hover:border-primary/40 hover:text-primary shadow-sm"
                  >
                    <Send className="h-3.5 w-3.5" />
                    Inject into Chat
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 3. Ranked Passage Cards Section */}
      <div className="space-y-4 pt-4">
        <div className="flex items-center justify-between px-2">
          <h4 className="text-xs font-bold uppercase tracking-[0.3em] text-muted-foreground flex items-center gap-2">
            <Code className="h-3.5 w-3.5 text-primary" />
            Ranked Intelligence Units
          </h4>
          <span className="text-[10px] font-bold text-muted-foreground/60 uppercase tracking-widest">{results.length} units extracted</span>
        </div>

        {results.length > 0 ? (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            {results.map((result, index) => (
              <ResultCard key={result.id || `${result.url}-${index}`} result={result} index={index} onSend={sendToChat} />
            ))}
          </div>
        ) : (
          <div className="rounded-3xl border border-dashed border-border/60 bg-card/60 p-12 text-center">
            <p className="text-sm font-medium text-muted-foreground">No specific passages were ranked.</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Full source content is still available in the intelligence explorer above.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function SourcesPanel({ response }: PanelProps) {
  const sources = response.sources || [];
  const initialActiveSourceIndex = useMemo(() => getMostRelevantSourceIndex(sources), [sources]);
  const [activeSourceIndex, setActiveSourceIndex] = useState(initialActiveSourceIndex);
  const [sourceViewMode, setSourceViewMode] = useState<ViewMode>('snippet');

  const featuredSource = useMemo(
    () => sources[Math.min(activeSourceIndex, Math.max(0, sources.length - 1))],
    [activeSourceIndex, sources],
  );

  React.useEffect(() => {
    setActiveSourceIndex(initialActiveSourceIndex);
  }, [initialActiveSourceIndex, sources]);

  if (sources.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-border/60 bg-card/60 p-12 text-center text-muted-foreground">
        No live sources were returned for this query.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-border/60 bg-card/90 overflow-hidden shadow-[0_24px_60px_rgba(0,0,0,0.16)]">
        <div className="bg-muted/20 px-6 py-5 border-b border-border/60">
           <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-1">
                <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground font-bold">Deep Source Inspection</p>
                <h3 className="text-2xl font-semibold text-foreground leading-tight">
                  {featuredSource?.title || 'Source Explorer'}
                </h3>
              </div>
              <div className="flex items-center gap-3">
                 <button
                   onClick={() => setActiveSourceIndex((c) => Math.max(0, c - 1))}
                   disabled={activeSourceIndex === 0}
                   className="p-2 rounded-full border border-border/60 hover:bg-muted disabled:opacity-30 transition-colors"
                 >
                    <AlignLeft className="h-4 w-4 rotate-180" />
                 </button>
                 <span className="text-sm font-mono text-muted-foreground">{activeSourceIndex + 1} / {sources.length}</span>
                 <button
                   onClick={() => setActiveSourceIndex((c) => Math.min(sources.length - 1, c + 1))}
                   disabled={activeSourceIndex === sources.length - 1}
                   className="p-2 rounded-full border border-border/60 hover:bg-muted disabled:opacity-30 transition-colors"
                 >
                    <AlignLeft className="h-4 w-4" />
                 </button>
              </div>
           </div>
        </div>

        <div className="grid gap-0 xl:grid-cols-[320px_1fr]">
          <div className="border-r border-border/60 bg-muted/5">
             <div className="p-4 border-b border-border/40">
                <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Captured Domains</p>
             </div>
             <div className="max-h-[32rem] overflow-auto custom-scrollbar">
                {sources.map((s, i) => (
                  <button
                    key={s.id || i}
                    onClick={() => setActiveSourceIndex(i)}
                    className={`w-full p-4 text-left border-b border-border/40 transition-all ${i === activeSourceIndex ? 'bg-primary/5 border-l-4 border-l-primary' : 'hover:bg-muted/30 border-l-4 border-l-transparent'}`}
                  >
                    <p className={`text-[10px] font-bold uppercase tracking-wider mb-1 ${i === activeSourceIndex ? 'text-primary' : 'text-muted-foreground'}`}>
                      {s.domain || domainFromUrl(s.url)}
                    </p>
                    <p className={`text-sm font-medium truncate ${i === activeSourceIndex ? 'text-foreground' : 'text-muted-foreground/80'}`}>{s.title}</p>
                  </button>
                ))}
             </div>
          </div>

          <div className="flex flex-col">
             <div className="flex items-center justify-between border-b border-border/60 bg-muted/10 px-5 py-3">
                <div className="flex gap-4">
                  <ViewToggle active={sourceViewMode === 'snippet'} onClick={() => setSourceViewMode('snippet')} label="Readable" icon={<AlignLeft className="h-3 w-3" />} />
                  <ViewToggle active={sourceViewMode === 'markdown'} onClick={() => setSourceViewMode('markdown')} label="Markdown" icon={<FileText className="h-3 w-3" />} />
                  <ViewToggle active={sourceViewMode === 'json'} onClick={() => setSourceViewMode('json')} label="Raw JSON" icon={<Code className="h-3 w-3" />} />
                </div>
             </div>

             <div className="p-6 overflow-auto max-h-[32rem] custom-scrollbar">
                {sourceViewMode === 'snippet' && (
                  <p className="whitespace-pre-wrap break-words text-sm leading-8 text-muted-foreground/90">
                    {featuredSource?.content || featuredSource?.snippet || 'No readable excerpt returned.'}
                  </p>
                )}
                {sourceViewMode === 'markdown' && (
                  <pre className="whitespace-pre-wrap break-words text-xs leading-6 text-foreground/90 font-mono bg-muted/5 p-5 rounded-2xl border border-border/40">
                    {featuredSource?.markdown || featuredSource?.full_content || 'Markdown content unavailable.'}
                  </pre>
                )}
                {sourceViewMode === 'json' && (
                  <pre className="text-[11px] leading-5 text-foreground/80 font-mono bg-muted/5 p-5 rounded-2xl border border-border/40">
                    {JSON.stringify(featuredSource, null, 2)}
                  </pre>
                )}
             </div>

             <div className="p-6 pt-0 mt-auto flex gap-3">
               <button onClick={() => sendToChat(featuredSource)} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-primary text-primary-foreground text-xs font-bold uppercase tracking-wider shadow-lg hover:scale-105 active:scale-95 transition-all">
                  <Send className="h-3.5 w-3.5" /> Inject into Conversation
               </button>
               {featuredSource?.url && (
                  <a href={featuredSource.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-border/60 hover:bg-muted text-xs font-bold uppercase tracking-wider text-muted-foreground transition-all">
                     <ExternalLink className="h-3.5 w-3.5" /> Visit Original
                  </a>
               )}
             </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ResultCard({ result, index, onSend }: { result: SearchResultItem; index: number; onSend: (item: any) => void }) {
  const [viewMode, setViewMode] = useState<ViewMode>('snippet');

  return (
    <article className="group relative rounded-3xl border border-border/60 bg-card/90 p-5 shadow-[0_18px_50px_rgba(0,0,0,0.16)] transition-all duration-300 hover:border-primary/40 hover:shadow-2xl">
      <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity z-10">
        <button 
          onClick={() => onSend(result)}
          className="p-2.5 rounded-full bg-primary text-primary-foreground shadow-lg hover:scale-110 active:scale-95 transition-all"
          title="Inject into chat"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
      
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
              {index + 1}
            </span>
            <span className="text-[10px] font-bold uppercase tracking-[0.25em] text-muted-foreground">
              {result.domain || domainFromUrl(result.url) || 'INTELLIGENCE UNIT'}
            </span>
          </div>
          <h5 className="text-base font-semibold leading-relaxed text-foreground pr-8">
            {result.title}
          </h5>
        </div>
        {typeof result.score === 'number' && (
          <div className="rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-[10px] font-bold text-primary">
            {(result.score * 100).toFixed(0)}%
          </div>
        )}
      </div>

      <div className="mt-4 rounded-2xl border border-border/40 bg-background/50 overflow-hidden">
        <div className="flex items-center gap-3 border-b border-border/40 bg-muted/20 px-3 py-1.5">
          {(['snippet', 'markdown', 'json'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`text-[9px] font-bold uppercase tracking-widest transition-colors px-2 py-1 rounded ${
                viewMode === mode ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        <div className="p-4 overflow-auto max-h-48 custom-scrollbar min-h-[6rem]">
          {viewMode === 'snippet' && (
            <p className="whitespace-pre-wrap break-words text-xs leading-6 text-muted-foreground/90 font-medium">
              {result.snippet || result.content || 'No unit content preview available.'}
            </p>
          )}
          {viewMode === 'markdown' && (
            <pre className="whitespace-pre-wrap break-words text-[10px] leading-5 text-foreground/90 font-mono">
              {result.markdown || result.content || 'Markdown source not available for this unit.'}
            </pre>
          )}
          {viewMode === 'json' && (
            <pre className="text-[10px] leading-4 text-foreground/80 font-mono">
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      </div>

      <a
        href={result.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-4 inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest text-primary transition-all hover:gap-2"
      >
        Source Access <ExternalLink className="h-3 w-3" />
      </a>
    </article>
  );
}

export function ExtractedDataPanel({ response }: PanelProps) {
  const sections = getPayloadSections(response);
  const hasCombinedPayload =
    sections.length > 0 ||
    Boolean(response.summary) ||
    Boolean(response.sources?.length) ||
    Boolean(response.results?.length);

  if (!hasCombinedPayload) {
    return (
      <div className="rounded-3xl border border-dashed border-border/60 bg-card/60 p-12 text-center text-muted-foreground">
        No structured search data was captured during this crawl.
      </div>
    );
  }

  const copiedPayload = {
    summary: response.summary,
    query: response.query,
    mode: response.mode,
    provider: response.provider,
    sources: response.sources,
    results: response.results,
    extractedData: response.extractedData,
    metadata: response.metadata,
    diagnostics: response.diagnostics,
  };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(copiedPayload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `karen-intel-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadMarkdown = () => {
    let md = `# Intelligent Search Intelligence: ${response.query || 'Untitled'}\n\n`;
    md += `## Synthesis\n${response.summary || 'No summary available.'}\n\n`;
    
    if (response.sources && response.sources.length > 0) {
      md += `## Verified Sources (${response.sources.length})\n\n`;
      response.sources.forEach((s, i) => {
        md += `### ${i + 1}. ${s.title || s.url}\n`;
        md += `**Domain:** ${s.domain || domainFromUrl(s.url)}\n`;
        md += `**URL:** ${s.url}\n\n`;
        md += `#### Intelligence Units\n${s.markdown || s.full_content || s.content || s.snippet || 'No content captured.'}\n\n`;
        if (s.extracted_data) {
          md += `#### Extracted Data\n\`\`\`json\n${JSON.stringify(s.extracted_data, null, 2)}\n\`\`\`\n\n`;
        }
        md += `---\n\n`;
      });
    }
    
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `karen-intel-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border/60 bg-card/90 p-6 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground font-bold">Intelligence Payload</p>
            <h3 className="text-xl font-semibold text-foreground">Deep Data View</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => navigator.clipboard.writeText(JSON.stringify(copiedPayload, null, 2))}
              className="flex items-center gap-2 px-4 py-2 rounded-full border border-border/60 hover:bg-muted text-[10px] font-bold uppercase tracking-wider transition-all"
            >
              <Code className="h-3.5 w-3.5" /> Copy JSON
            </button>
            <button
              onClick={downloadJson}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 text-[10px] font-bold uppercase tracking-wider transition-all"
            >
              <Download className="h-3.5 w-3.5" /> JSON
            </button>
            <button
              onClick={downloadMarkdown}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-primary text-primary-foreground hover:scale-105 text-[10px] font-bold uppercase tracking-wider transition-all shadow-md"
            >
              <Download className="h-3.5 w-3.5" /> Markdown
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <MetricPill label="Schema" value={response.mode || 'default'} />
          <MetricPill label="Payload Size" value={`${(JSON.stringify(copiedPayload).length / 1024).toFixed(1)} KB`} />
          <MetricPill label="Status" value="Verified" />
        </div>
      </div>

      {sections.map((section) => (
        <JsonSection key={section.title} title={section.title} data={section.data} />
      ))}
    </div>
  );
}

export function InsightsPanel({ response }: PanelProps) {
  const insights = response.insights || [];

  if (insights.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-border/60 bg-card/60 p-12 text-center text-muted-foreground">
        No specialist insights available for this intelligence gather.
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {insights.map((insight, i) => (
        <div
          key={i}
          className="group relative rounded-3xl border border-border/60 bg-card/85 p-6 text-sm leading-7 text-foreground/90 shadow-sm transition-all hover:border-primary/30 hover:shadow-lg"
        >
          <div className="absolute top-6 left-2 w-1 h-8 bg-primary/30 rounded-full group-hover:bg-primary transition-all" />
          <div className="pl-4">
            {insight}
          </div>
        </div>
      ))}
    </div>
  );
}

export function DiagnosticsPanel({ response }: PanelProps) {
  const diag = response.diagnostics;

  if (!diag) {
    return (
      <div className="rounded-3xl border border-dashed border-border/60 bg-card/60 p-12 text-center text-muted-foreground">
        Intelligence diagnostics not provided.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="rounded-3xl border border-border/60 bg-card/90 p-6 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
        <h4 className="text-[11px] font-bold uppercase tracking-[0.3em] text-muted-foreground mb-5">
          Orchestration Metadata
        </h4>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <MetricRow label="Search Mode" value={diag.mode} />
          <MetricRow label="Strategy" value={diag.strategy || 'standard'} />
          <MetricRow label="Pipeline Latency" value={diag.latencyMs ? `${diag.latencyMs}ms` : 'real-time'} />
          <MetricRow label="URLs Identified" value={diag.urlsFound ?? 0} />
          <MetricRow label="Pages Processed" value={diag.pagesCrawled ?? 0} />
          <MetricRow label="Units Produced" value={diag.chunksProduced ?? 0} />
        </dl>
      </div>

      <div className={`rounded-3xl border p-6 shadow-[0_24px_60px_rgba(0,0,0,0.18)] ${
        diag.degraded
          ? 'border-amber-500/30 bg-amber-500/10'
          : 'border-border/60 bg-card/90'
      }`}>
        <h4 className="text-[11px] font-bold uppercase tracking-[0.3em] text-muted-foreground mb-5">
          Connectivity Status
        </h4>
        <div className="space-y-3">
          <MetricRow label="Node Health" value={diag.degraded ? 'Degraded' : 'Nominal'} />
          <MetricRow label="Critical Warnings" value={diag.warnings?.length ?? 0} />
        </div>
        {diag.warnings && diag.warnings.length > 0 && (
          <div className="mt-5 space-y-2">
            {diag.warnings.map((warning, index) => (
              <div
                key={index}
                className="rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200/80 font-medium leading-5"
              >
                ⚠️ {warning}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-border/40 bg-background/40 px-4 py-3 text-xs">
      <dt className="text-muted-foreground font-bold uppercase tracking-widest text-[9px]">{label}</dt>
      <dd className="font-bold text-foreground">{value}</dd>
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/80 px-3 py-1.5 text-[10px] text-muted-foreground font-bold shadow-sm">
      <span className="uppercase tracking-[0.2em] opacity-60">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}

function domainFromUrl(url: string) {
  try {
    return new URL(url).hostname.replace('www.', '');
  } catch {
    return 'Web Source';
  }
}

function getMostRelevantSourceIndex(sources: SearchSourceItem[]) {
  if (!sources.length) return 0;
  let bestIndex = 0;
  let bestScore = -1;
  sources.forEach((source, index) => {
    const score = source.relevanceScore ?? 0;
    if (score > bestScore) {
      bestIndex = index;
      bestScore = score;
    }
  });
  return bestIndex;
}

function getPayloadSections(response: IntelligentSearchResponse) {
  const sections: Array<{ title: string; data: unknown }> = [];
  if (response.liveSearch && Object.keys(response.liveSearch).length > 0) {
    sections.push({ title: 'Live retrieval manifest', data: response.liveSearch });
  }
  if (response.extractedData && Object.keys(response.extractedData).length > 0) {
    sections.push({ title: 'Structured extraction results', data: response.extractedData });
  }
  if (response.metadata && Object.keys(response.metadata).length > 0) {
    sections.push({ title: 'Orchestration metadata', data: response.metadata });
  }
  return sections;
}

function JsonSection({ title, data }: { title: string; data: unknown }) {
  return (
    <div className="overflow-hidden rounded-3xl border border-border/60 bg-card/90 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
      <div className="border-b border-border/60 bg-muted/20 px-6 py-4 flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-muted-foreground">{title}</span>
        <div className="flex gap-2">
           <div className="h-1.5 w-1.5 rounded-full bg-primary/40" />
           <div className="h-1.5 w-1.5 rounded-full bg-primary/20" />
        </div>
      </div>
      <pre className="max-h-[70vh] overflow-auto p-6 text-[11px] leading-6 text-foreground/90 font-mono custom-scrollbar">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
