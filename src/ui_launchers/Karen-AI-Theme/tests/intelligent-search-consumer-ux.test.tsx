import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { ResultsPanel } from '../src/plugin_repo/intelligent-search/components/Panels';
import type { IntelligentSearchResponse } from '../src/plugin_repo/intelligent-search/types';

const history = [
  {
    id: 'jamaica',
    url: 'https://en.wikipedia.org/wiki/History_of_Jamaica',
    domain: 'en.wikipedia.org',
    title: 'History of Jamaica',
    snippet: 'Jamaica gained independence in 1962.',
    readable_content: 'Jamaica gained independence in 1962. People shaped the island.',
    full_content: 'Main menu Related posts Wikipedia sidebar',
    evidence_level: 'fetched_page' as const,
  },
  {
    id: 'britannica',
    url: 'https://www.britannica.com/place/Jamaica',
    domain: 'britannica.com',
    title: 'Jamaica history',
    snippet: 'Independent Caribbean history.',
    evidence_level: 'search_snippet' as const,
  },
];

function response(): IntelligentSearchResponse {
  return {
    summary: 'Found 1 fetched source for this search. Research evidence is ready, but Karen has not generated an answer.',
    query: 'What is the history of Jamaica?',
    mode: 'general',
    status: 'ok',
    sources: [history[0], history[0], history[1]],
    results: [
      { id: 'x1', url: history[0].url, title: 'History of Jamaica', snippet: 'Passage one' },
      { id: 'x2', url: history[0].url, title: 'History of Jamaica', snippet: 'Passage two' },
    ],
  };
}

afterEach(cleanup);

describe('Intelligent Search human-first evidence presentation', () => {
  it('shows each source once, without ranked-passage machinery or raw Markdown', () => {
    render(<ResultsPanel response={response()} />);
    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect(screen.getByText('Your research sources')).toBeTruthy();
    expect(screen.queryByText('Ranked Intelligence Units')).toBeNull();
    expect(screen.queryByText(/Main menu Related posts/)).toBeNull();
    expect(screen.queryByText(/Passage one/)).toBeNull();
    expect(screen.getByText('Link discovered')).toBeTruthy();
    expect(screen.getByText('Page retrieved')).toBeTruthy();
  });

  it('opens a readable preview without leaking original webpage navigation', () => {
    render(<ResultsPanel response={response()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Read source' }));
    expect(screen.getByText(/People shaped the island/)).toBeTruthy();
    expect(screen.queryByText(/Main menu Related posts/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByText(/People shaped the island/)).toBeNull();
  });

  it('keeps the full untrusted extraction available only after explicit selection', () => {
    render(<ResultsPanel response={response()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Read source' }));
    expect(screen.queryByText(/Main menu Related posts/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'View original extracted text' }));
    expect(screen.getByText(/Main menu Related posts/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Return to readable excerpts' }));
    expect(screen.queryByText(/Main menu Related posts/)).toBeNull();
  });

  it('never dumps raw markup from historical responses without readable_content', () => {
    const legacy = response();
    const rawOnly = {
      ...history[0],
      readable_content: undefined,
      content: 'Historical facts about Jamaica.',
      snippet: 'History of Jamaica.',
    };
    legacy.sources = [rawOnly];
    render(<ResultsPanel response={legacy} />);
    fireEvent.click(screen.getByRole('button', { name: 'Read source' }));
    expect(screen.getByText('Historical facts about Jamaica.')).toBeTruthy();
    expect(screen.queryByText(/Main menu Related posts/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'View original extracted text' }));
    expect(screen.getByText(/Main menu Related posts/)).toBeTruthy();
  });

  it('shows an honest error when the canonical chat has not accepted the draft', () => {
    render(<ResultsPanel response={response()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Prepare a question for Karen using these sources' }));
    expect(screen.getByRole('alert').textContent).toContain('chat is not ready');
  });

  it('prepares a user draft and never auto-submits untrusted source content', () => {
    const events: CustomEvent[] = [];
    const handler = (event: Event) => {
      events.push(event as CustomEvent);
      event.preventDefault();
    };
    window.addEventListener('karen:inject-message', handler);
    try {
      render(<ResultsPanel response={response()} />);
      fireEvent.click(screen.getByRole('button', { name: 'Prepare a question for Karen using these sources' }));
      expect(events).toHaveLength(1);
      expect(events[0].cancelable).toBe(true);
      expect(events[0].defaultPrevented).toBe(true);
      expect(events[0].detail.role).toBe('user');
      expect(events[0].detail.autoSubmit).toBe(false);
      expect(events[0].detail.content).toContain('Question: What is the history of Jamaica?');
      expect(events[0].detail.content).toContain('untrusted research leads');
      expect(events[0].detail.content).not.toContain('Main menu');
    } finally {
      window.removeEventListener('karen:inject-message', handler);
    }
  });
});
