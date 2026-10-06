import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import RichResultWorkspace from '@/components/chat/RichResultWorkspace';
import type { ChatMessage } from '@/lib/types';

describe('RichResultWorkspace', () => {
  it('stays absent when the backend reported no rich result', () => {
    const message: ChatMessage = {
      id: 'm1',
      role: 'assistant',
      content: 'Plain response',
      timestamp: new Date(),
      status: 'completed',
    };

    const { container } = render(<RichResultWorkspace message={message} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders only backend-provided artifacts, attachments, structure, and evidence', () => {
    const message: ChatMessage = {
      id: 'm2',
      role: 'assistant',
      content: 'Completed',
      timestamp: new Date(),
      status: 'completed',
      structuredContent: {
        summary: 'Two findings',
      },
      artifacts: [
        {
          id: 'artifact-1',
          title: 'Research brief',
          type: 'document',
          content: 'Canonical artifact body',
        },
      ],
      attachments: [
        {
          id: 'attachment-1',
          name: 'evidence.csv',
          mime_type: 'text/csv',
        },
      ],
      sources: [
        {
          id: 'source-1',
          url: 'https://example.com/source',
          title: 'Evidence source',
          snippet: 'Supporting evidence',
          index: 1,
        },
      ],
    };

    render(<RichResultWorkspace message={message} />);

    expect(screen.getByText('Workspace')).toBeTruthy();
    expect(screen.getByText('Research brief')).toBeTruthy();
    expect(screen.getByText('Canonical artifact body')).toBeTruthy();
    expect(screen.getByText('evidence.csv')).toBeTruthy();
    expect(screen.getByText('Evidence source')).toBeTruthy();
    expect(screen.getByText('Two findings')).toBeTruthy();
  });
  it('does not turn unsafe backend URLs into navigable links', () => {
    const message: ChatMessage = {
      id: 'm3',
      role: 'assistant',
      content: 'Completed',
      timestamp: new Date(),
      status: 'completed',
      sources: [
        {
          id: 'source-unsafe',
          url: 'javascript:alert(1)',
          title: 'Unsafe source',
          snippet: 'Must remain text only',
          index: 1,
        },
      ],
      artifacts: [
        {
          id: 'artifact-unsafe',
          title: 'Local path artifact',
          type: 'file',
          url: 'file:///tmp/private.txt',
        },
      ],
    };

    render(<RichResultWorkspace message={message} />);

    expect(screen.getByText('Unsafe source')).toBeTruthy();
    expect(screen.queryByRole('link', { name: /unsafe source/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /open artifact/i })).toBeNull();
  });
});
