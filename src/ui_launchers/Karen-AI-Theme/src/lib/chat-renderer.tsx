"use client";

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';

export interface ChatRenderedContentProps {
  content: string;
  emphasize?: boolean;
}

export const getChatContentClassName = (emphasize = false): string =>
  `prose prose-sm md:prose-base dark:prose-invert max-w-none ${
    emphasize ? 'text-foreground font-medium' : ''
  }`;

export const chatMarkdownComponents = {
  p: (props: React.ComponentProps<'p'>) => (
    <p className="mb-2 last:mb-0 whitespace-pre-wrap leading-relaxed" {...props} />
  ),
  a: (props: React.ComponentProps<'a'>) => (
    <a
      className="text-blue-400 hover:underline font-medium"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  ul: (props: React.ComponentProps<'ul'>) => (
    <ul className="list-disc pl-5 mb-3 space-y-1" {...props} />
  ),
  ol: (props: React.ComponentProps<'ol'>) => (
    <ol className="list-decimal pl-5 mb-3 space-y-1" {...props} />
  ),
  li: (props: React.ComponentProps<'li'>) => <li className="mb-1" {...props} />,
  img: ({ src, alt, ...props }: React.ComponentProps<'img'>) => {
    const resolvedSrc = typeof src === 'string' ? src.trim() : src;
    if (!resolvedSrc) return null;
    return (
      <img
        src={resolvedSrc}
        alt={alt ?? ''}
        className="my-3 max-w-full rounded-xl border border-border/60"
        {...props}
      />
    );
  },
  code: ({ className, children, ...props }: React.ComponentProps<'code'>) => {
    const match = /language-(\w+)/.exec(className || '');
    const isInline = !match && !String(children).includes('\n');
    return !isInline ? (
      <div className="relative group my-3">
        <pre className="p-3 md:p-4 bg-[#1e1e1e] text-[#d4d4d4] rounded-xl overflow-x-auto font-mono text-xs md:text-sm border border-white/5">
          <code className={className} {...props}>
            {children}
          </code>
        </pre>
      </div>
    ) : (
      <code
        className="bg-muted px-1.5 py-0.5 rounded text-[0.9em] font-mono text-primary-foreground/90 bg-primary-foreground/10"
        {...props}
      >
        {children}
      </code>
    );
  },
};

export function ChatRenderedContent({
  content,
  emphasize = false,
}: ChatRenderedContentProps) {
  return (
    <div className={getChatContentClassName(emphasize)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={chatMarkdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
