import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../../src/lib/api';

function streamResponse(payload: string) {
  const chunks = [new TextEncoder().encode(payload)];
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'x-correlation-id': 'corr-123' }),
    body: {
      getReader: () => ({
        read: vi.fn()
          .mockResolvedValueOnce({ done: false, value: chunks[0] })
          .mockResolvedValue({ done: true, value: undefined }),
        releaseLock: vi.fn(),
      }),
    },
  };
}

describe('canonical chat SSE terminal events', () => {
  const callbacks = {
    onError: vi.fn<(message: string, metadata?: Record<string, unknown>) => void>(),
    onComplete: vi.fn(),
    onContent: vi.fn(),
    onDone: vi.fn(),
  };

  beforeEach(() => {
    Object.values(callbacks).forEach((mock) => mock.mockClear());
    vi.spyOn(
      apiClient as unknown as { getAuthHeaders: () => Promise<Record<string, string>> },
      'getAuthHeaders',
    ).mockResolvedValue({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function consume(sse: string) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(sse)));
    await apiClient.postStream('/api/chat/stream', { message: 'hello' }, callbacks);
  }

  it('rejects premature DONE without marking a model reply complete', async () => {
    await consume('data: {"type":"status","content":"Working"}\n\ndata: [DONE]\n\n');
    expect(callbacks.onComplete).not.toHaveBeenCalled();
    expect(callbacks.onDone).not.toHaveBeenCalled();
    expect(callbacks.onError).toHaveBeenCalledOnce();
    expect(callbacks.onError.mock.calls[0][1]).toMatchObject({
      error_code: 'CHAT_STREAM_INCOMPLETE',
      correlation_id: 'corr-123',
    });
  });

  it('rejects EOF after a status-only partial SSE stream', async () => {
    await consume('data: {"type":"status","content":"Working"}\n\n');
    expect(callbacks.onComplete).not.toHaveBeenCalled();
    expect(callbacks.onError.mock.calls[0][0]).toContain(
      'without a runtime completion',
    );
  });

  it('rejects trailing truncated events rather than hiding a parsing failure', async () => {
    await consume('data: {"type":"content","content":"partial"');
    expect(callbacks.onError.mock.calls[0][0]).toContain('incomplete SSE event');
  });

  it('ignores initial SSE transport comments without starting a progress status', async () => {
    await consume(
      ': stream_connected\\n\\n' +
      'data: {"type":"content","content":"Hello"}\\n\\n' +
      'data: {"type":"complete","content":""}\\n\\n',
    );
    expect(callbacks.onContent).toHaveBeenCalledWith('Hello');
    expect(callbacks.onComplete).toHaveBeenCalledOnce();
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  it('preserves successful backend content and true terminal completion', async () => {
    await consume(
      'data: {"type":"content","content":"Hello"}\n\n' +
      'data: {"type":"complete","content":"","metadata":{"correlation_id":"corr-123"}}\n\n',
    );
    expect(callbacks.onContent).toHaveBeenCalledWith('Hello');
    expect(callbacks.onComplete).toHaveBeenCalledOnce();
    expect(callbacks.onError).not.toHaveBeenCalled();
  });

  it('forwards upstream failure details without inventing fallback text', async () => {
    await consume(
      'data: {"type":"error","content":"Runtime unavailable",' +
      '"metadata":{"error_code":"CHAT_EMPTY_STREAM","correlation_id":"corr-123"}}\n\n',
    );
    expect(callbacks.onComplete).not.toHaveBeenCalled();
    expect(callbacks.onError).toHaveBeenCalledWith(
      'Runtime unavailable',
      expect.objectContaining({
        error_code: 'CHAT_EMPTY_STREAM',
        correlation_id: 'corr-123',
      }),
    );
  });
});
