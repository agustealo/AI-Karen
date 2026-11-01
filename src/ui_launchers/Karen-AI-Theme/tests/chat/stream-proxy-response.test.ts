import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NextRequest } from 'next/server';
import { POST } from '../../src/app/api/chat/stream/route';

vi.mock('../../src/app/api/_lib/backend-proxy', () => ({
  getBackendBaseUrl: () => 'http://api:8000',
  getBackendTargetStatus: () => 'configured',
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
  it('sends exactly one POST to the configured backend when transport fails', async () => {
    const fetchSpy = vi.fn().mockRejectedValue(
      new Error('Sensitive failed destination: http://internal:secret@private-service'),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const response = await POST(request());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe('http://api:8000/api/chat/stream');
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(init.redirect).toBe('manual');
    expect(init.cache).toBe('no-store');
    const text = await response.text();
    expect(response.status).toBe(502);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(text).toContain('CHAT_STREAM_BACKEND_UNAVAILABLE');
    expect(text).not.toContain('private-service');
    expect(text).not.toContain('secret');
  });

  it('does not retry a 404 response against another backend', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response('{"detail":"Not Found"}', {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const response = await POST(request());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: 'Not Found' });
  });

  it('does not follow or expose upstream execution redirects', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location: 'http://host.docker.internal:8000/private' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const response = await POST(request());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(502);
    expect(response.headers.get('location')).toBeNull();
    const payload = await response.json();
    expect(payload.error_code).toBe('CHAT_STREAM_UPSTREAM_REDIRECT');
    expect(JSON.stringify(payload)).not.toContain('host.docker.internal');
  });

  it('does not leak an upstream HTML gateway response into chat JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('<html>Internal: token=not-public</html>', {
        status: 502,
        headers: { 'content-type': 'text/html' },
      }),
    ));
    const response = await POST(request());
    expect(response.status).toBe(502);
    const data = await response.json();
    expect(data.error_code).toBe('CHAT_STREAM_UPSTREAM_REJECTED');
    expect(JSON.stringify(data)).not.toContain('not-public');
  });

  it('preserves a canonical authentication rejection without alternate provider selection', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response('{"detail":"Not authenticated"}', {
        status: 401,
        headers: { 'content-type': 'application/json; charset=utf-8' },
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    const response = await POST(request());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(401);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({ detail: 'Not authenticated' });
  });

  it('contains no route-level streaming backend fallback registry', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const source = readFileSync(
      resolve(process.cwd(), 'src/app/api/chat/stream/route.ts'),
      'utf8',
    );
    expect(source).not.toContain('host.docker.internal');
    expect(source).not.toContain('fallbackUpstreamUrls');
    expect(source).not.toContain('candidateUrls');
    expect(source).toContain('getBackendBaseUrl()');
  });

});
