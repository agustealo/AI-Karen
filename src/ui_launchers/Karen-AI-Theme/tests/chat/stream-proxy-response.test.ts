import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NextRequest } from 'next/server';
import { POST } from '../../src/app/api/chat/stream/route';

vi.mock('../../src/app/api/_lib/backend-proxy', () => ({
  getBackendBaseUrl: () => 'http://api:8000',
  sanitizeHeaders: () => new Headers({ 'content-type': 'application/json' }),
}));

const request = () =>
  new Request('http://localhost:3000/api/chat/stream', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: 'hello' }),
  }) as NextRequest;

describe('canonical Next.js SSE proxy response contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('rejects an upstream HTTP 200 JSON response instead of disguising it as SSE', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('{"detail":"unexpected"}', {
        status: 200,
        headers: {
          'content-type': 'application/json',
          'x-correlation-id': 'backend-1',
        },
      }),
    ));
    const response = await POST(request());
    expect(response.status).toBe(502);
    const payload = await response.json();
    expect(payload).toMatchObject({
      error_code: 'CHAT_STREAM_UPSTREAM_NOT_SSE',
      correlation_id: 'backend-1',
    });
  });

  it('relays a canonical SSE success unchanged', async () => {
    const canonical = 'data: {"type":"complete","content":""}\n\ndata: [DONE]\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(canonical, {
        status: 200,
        headers: {
          'content-type': 'text/event-stream; charset=utf-8',
          'x-correlation-id': 'backend-2',
        },
      }),
    ));
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/event-stream');
    expect(response.headers.get('x-correlation-id')).toBe('backend-2');
    expect(await response.text()).toBe(canonical);
  });

  it('returns a correlated transport error on truncated upstream SSE', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('data: {"type":"status","content":"Working"}\n\n', {
        status: 200,
        headers: {
          'content-type': 'text/event-stream',
          'x-correlation-id': 'backend-3',
        },
      }),
    ));
    const response = await POST(request());
    const body = await response.text();
    expect(body).toContain('CHAT_STREAM_UPSTREAM_TERMINATED');
    expect(body).toContain('backend-3');
    expect(body).not.toContain('"type":"complete"');
  });
});
