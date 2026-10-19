import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NextRequest } from 'next/server';
import { POST } from '../../src/app/api/chat/ag-ui/route';

vi.mock('../../src/app/api/_lib/backend-proxy', () => ({
  getBackendBaseUrl: () => 'http://api:8000',
  sanitizeHeaders: () => new Headers({ 'content-type': 'application/json' }),
}));

const request = () => new Request('http://localhost:3000/api/chat/ag-ui', {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    threadId: 'thread-1',
    runId: 'run-1',
    messages: [{ role: 'user', content: 'hello' }],
  }),
}) as NextRequest;

describe('AG-UI stream proxy', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('accepts a verified terminal event', async () => {
    const payload = 'data: {"type":"RUN_FINISHED"}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(payload, {
      headers: { 'content-type': 'text/event-stream' },
    })));
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(await response.text()).toBe(payload);
  });

  it('fails closed when the upstream stream ends without completion', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', {
      headers: { 'content-type': 'text/event-stream' },
    })));
    const output = await (await POST(request())).text();
    expect(output).toContain('RUN_ERROR');
    expect(output).toContain('CHAT_STREAM_UPSTREAM_TERMINATED');
  });
});
