import React, { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useRequestHandlers } from '@/components/chat/const/requestHandlers';

function CancellationHarness() {
  const inFlight = useRef(true);
  const controller = useRef<AbortController | null>(new AbortController());
  const [status, setStatus] = useState('Generating response');
  const [loading, setLoading] = useState(true);
  const { stopActiveRequest } = useRequestHandlers(inFlight, controller, setStatus, setLoading);

  return (
    <div>
      <button onClick={stopActiveRequest}>Stop</button>
      <button onClick={() => {
        inFlight.current = false;
        controller.current = null;
        setStatus('');
      }}>Finish cleanup</button>
      <button onClick={() => { controller.current = null; setLoading(true); }}>Restore orphan state</button>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="status">{status}</span>
      <span data-testid="locked">{String(inFlight.current)}</span>
      <span data-testid="aborted">{String(controller.current?.signal.aborted ?? false)}</span>
    </div>
  );
}

describe('chat request cancellation ownership', () => {
  it('aborts the active request without releasing its submit lock prematurely', () => {
    render(<CancellationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(screen.getByTestId('locked').textContent).toBe('true');
    expect(screen.getByTestId('aborted').textContent).toBe('true');
    expect(screen.getByTestId('status').textContent).toBe('Request cancelled by user.');
    fireEvent.click(screen.getByRole('button', { name: 'Finish cleanup' }));
    expect(screen.getByTestId('locked').textContent).toBe('false');
    expect(screen.getByTestId('status').textContent).toBe('');
  });

  it('unlocks a restored in-flight snapshot without a live controller', () => {
    render(<CancellationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Restore orphan state' }));
    expect(screen.getByTestId('locked').textContent).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(screen.getByTestId('locked').textContent).toBe('false');
    expect(screen.getByTestId('loading').textContent).toBe('false');
    expect(screen.getByTestId('status').textContent).toBe('');
  });

  it('treats repeated Stop clicks as idempotent', () => {
    render(<CancellationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(screen.getByTestId('locked').textContent).toBe('true');
    expect(screen.getByTestId('aborted').textContent).toBe('true');
  });
});
