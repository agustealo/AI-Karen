import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ChatMessage } from '@/lib/types';
import { MessageBubble } from './MessageBubble';

const restoredMessage = (metadata: Record<string, unknown>): ChatMessage => ({
  id: 'restored-answer',
  role: 'assistant',
  content: 'The article supports this conclusion.',
  timestamp: new Date('2026-10-25T18:00:00Z'),
  metadata,
} as unknown as ChatMessage);

describe('restored assistant evidence', () => {
  it('renders persisted citation badge and grounded provenance without top-level citations', () => {
    const html = renderToStaticMarkup(
      <MessageBubble message={restoredMessage({
        answer_composition_status: 'grounded_model',
        citations: [{ url: 'https://example.org/article', title: 'Verified article' }],
        actual_provider: 'local',
        actual_model: 'verified-model',
      })} />,
    );
    expect(html).toContain('Verified grounded answer');
    expect(html).toContain('Show 1 source');
    expect(html).toContain('chat-evidence-status');
  });

  it('does not invent sources or a grounded status from absent metadata', () => {
    const html = renderToStaticMarkup(<MessageBubble message={restoredMessage({})} />);
    expect(html).not.toContain('Show 1 source');
    expect(html).not.toContain('Verified grounded answer');
  });

  it('does not turn unsafe persisted citation URLs into source badges', () => {
    const html = renderToStaticMarkup(
      <MessageBubble message={restoredMessage({
        citations: [{ url: 'javascript:alert(1)', title: 'Untrusted' }],
      })} />,
    );
    expect(html).not.toContain('Show 1 source');
  });
});
