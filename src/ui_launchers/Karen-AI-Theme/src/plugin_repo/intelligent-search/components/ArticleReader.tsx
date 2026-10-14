import React, { useEffect, useState } from 'react';
import { IntelligentSearchApi } from '../services/IntelligentSearchApi';
import type { SearchSourceItem } from '../types';

interface ArticleReaderProps {
  source: SearchSourceItem | undefined;
}

const headingPattern = /^(#{1,6})\s+(.+)$/;
const bulletPattern = /^\s*[-*+]\s+(.+)$/;
const numberedPattern = /^\s*\d+[.)]\s+(.+)$/;

/**
 * Render plain extracted source text as accessible reading blocks.
 * Content is always treated as untrusted text: no HTML injection, raw
 * markdown execution, iframe embedding, or network requests.
 */
export function ArticleReader({ source }: ArticleReaderProps) {
  if (!source) {
    return <p role="status" className="text-sm text-muted-foreground">Select a source to read.</p>;
  }

  const [storedArticle, setStoredArticle] = useState<{ id: string; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const articleId = source.article_id || null;
  const hasInlineComplete = source.article_complete === true && Boolean(source.full_content);

  useEffect(() => {
    let current = true;
    setStoredArticle(null);
    setLoadError(false);
    setLoading(false);
    if (!articleId || hasInlineComplete) return () => { current = false; };
    setLoading(true);
    IntelligentSearchApi.fetchArticle(articleId)
      .then(text => {
        if (current) setStoredArticle({ id: articleId, text });
      })
      .catch(() => {
        if (current) setLoadError(true);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [articleId, hasInlineComplete]);

  const fetchedText = storedArticle?.id === articleId ? storedArticle.text : null;
  const documentText = fetchedText || source.full_content || source.article_preview || source.content || source.snippet || '';
  const hasArticle = Boolean(fetchedText || source.full_content || source.article_preview);
  const complete = Boolean(fetchedText) || hasInlineComplete;
  const paragraphs = documentText.replace(/\r\n?/g, '\n').split(/\n\s*\n/).filter(Boolean);

  return (
    <article aria-label={`Reading ${source.title || 'source'}`} className="mx-auto w-full max-w-3xl space-y-5 text-foreground">
      <header className="space-y-2 border-b border-border/60 pb-5">
        <h3 className="text-2xl font-semibold leading-tight tracking-tight">{source.title || 'Untitled source'}</h3>
        <p className="text-xs text-muted-foreground break-all">{source.domain || source.url}</p>
        <p role="status" className="text-xs text-muted-foreground">
          {loading
            ? 'Loading the saved full article…'
            : complete
              ? 'Full article text available in this view.'
              : loadError
                ? 'Saved article could not be loaded. Showing available preview.'
                : !hasArticle
                  ? 'Discovery excerpt only. Full source content has not been provided.'
                  : 'Partial article preview. The full document is not available in this view.'}
        </p>
      </header>
      {paragraphs.length === 0 ? (
        <p role="status" className="text-sm text-muted-foreground">No readable source content is available.</p>
      ) : (
        <div className="space-y-5 text-base leading-8">
          {paragraphs.map((block, index) => {
            const lines = block.trim().split('\n');
            const heading = headingPattern.exec(lines[0].trim());
            if (heading && lines.length === 1) {
              const level = heading[1].length;
              return level <= 2
                ? <h4 key={index} className="pt-3 text-xl font-semibold leading-7">{heading[2]}</h4>
                : <h5 key={index} className="pt-2 text-lg font-semibold leading-7">{heading[2]}</h5>;
            }
            const bullets = lines.map(line => bulletPattern.exec(line));
            if (bullets.every(Boolean)) {
              return <ul key={index} className="list-disc space-y-2 pl-6">{bullets.map((entry, i) => <li key={i}>{entry?.[1]}</li>)}</ul>;
            }
            const numbered = lines.map(line => numberedPattern.exec(line));
            if (numbered.every(Boolean)) {
              return <ol key={index} className="list-decimal space-y-2 pl-6">{numbered.map((entry, i) => <li key={i}>{entry?.[1]}</li>)}</ol>;
            }
            return <p key={index} className="whitespace-pre-wrap break-words">{block}</p>;
          })}
        </div>
      )}
      {source.url && (
        <footer className="border-t border-border/60 pt-4 text-sm">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2">
            Read on original website
          </a>
        </footer>
      )}
    </article>
  );
}
