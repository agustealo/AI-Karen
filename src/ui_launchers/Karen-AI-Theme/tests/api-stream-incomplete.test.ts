import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../src/lib/api';

/**
 * Deterministic SSE transport faults, not mocked model success.
 * These tests cover the API parsing contract; real UX screenshots are owned
 * by e2e/ux-user-journeys.spec.ts and the governed capture rail.
 */
describe('chat SSE terminal provenance', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const streamResponse = (events: string[]): Response => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(encoder.encode(event));
        }
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'x-correlation-id': 'ux-incomplete-stream-test',
      },
    });
  };

  it.each([
    ['EOF after partial content', [
      'data: {"type":"content","content":"unfinished","correlation_id":"ux-incomplete-stream-test"}\n\n',
    ]],
    ['DONE without completion', [
      'data: {"type":"content","content":"unfinished","correlation_id":"ux-incomplete-stream-test"}\n\n',
      'data: [DONE]\n\n',
    ]],
    ['partial trailing SSE record', [
      'data: {"type":"content","content":"unfinished","correlation_id":"ux-incomplete-stream-test"}\n\n',
      'data: {"type":"complete","content":',
    ]],
  ])('rejects %s without completing a model response', async (_label, events) => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(events));
    vi.stubGlobal('fetch', fetchMock);
    const onContent = vi.fn();
    const onComplete = vi.fn();
    const onError = vi.fn();

    await apiClient.postStream('/api/chat/stream', { message: 'transport test' }, {
      onContent,
      onComplete,
      onError,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onContent).toHaveBeenCalledWith('unfinished');
    expect(onComplete).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        error_code: 'CHAT_STREAM_INCOMPLETE',
        error_type: 'IncompleteStream',
        correlation_id: 'ux-incomplete-stream-test',
        content_chunks_received: 1,
      }),
    );
  });

  it('accepts a genuine terminal completion event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"type":"content","content":"finished","correlation_id":"ux-incomplete-stream-test"}\n\n',
      'data: {"type":"complete","content":"finished","metadata":{"status":"completed"},"correlation_id":"ux-incomplete-stream-test"}\n\n',
    ])));
    const onError = vi.fn();
    const onComplete = vi.fn();
    await apiClient.postStream('/api/chat/stream', { message: 'terminal test' }, {
      onError,
      onComplete,
    });
    expect(onError).not.toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledOnce();
    expect(onComplete).toHaveBeenCalledWith({ status: 'completed' }, 'finished');
  });
});
