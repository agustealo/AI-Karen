import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NextRequest } from 'next/server';
import { POST } from '../../src/app/api/chat/ag-ui/route';

vi.mock('../../src/app/api/_lib/backend-proxy', () => ({
  getBackendBaseUrl: () => 'http://api:8000',
  sanitizeHeaders: () => new Headers(),
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

  it('forwards a JSON media type when the SDK omitted it and preserves the request body', async () => {
    const input = JSON.stringify({
      threadId: '4b6ecd10-26dc-554d-b20f-37222d9a978d',
      runId: 'fa2ba4ab-5c4d-4fb4-9c3d-fb4d80308984',
      protocolVersion: '1.0',
      state: {},
      messages: [{ id: '611ae4b5-1a08-4c07-98b1-b8ddd478b749', role: 'user', content: 'hi' }],
      tools: [],
      context: [],
      forwardedProps: {},
    });
    const upstream = vi.fn().mockResolvedValue(new Response('data: {"type":"RUN_FINISHED"}\\n\\n', {
      headers: { 'content-type': 'text/event-stream' },
    }));
    vi.stubGlobal('fetch', upstream);
    const browserRequest = new Request('http://localhost:3000/api/chat/ag-ui', {
      method: 'POST',
      body: input,
      headers: { 'content-type': 'text/plain' },
    }) as NextRequest;
    const response = await POST(browserRequest);
    expect(response.status).toBe(200);
    const forwarded = upstream.mock.calls[0][1] as RequestInit;
    const headers = forwarded.headers as Headers;
    expect(headers.get('content-type')).toBe('application/json');
    expect(headers.get('accept')).toBe('text/event-stream');
    expect(forwarded.body).toBe(input);
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

  it('recognizes a terminal event split across SSE data lines and network chunks', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":\n'));
        controller.enqueue(encoder.encode('data: "RUN_FINISHED"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      headers: { 'content-type': 'text/event-stream' },
    })));
    const output = await (await POST(request())).text();
    expect(output).not.toContain('CHAT_STREAM_UPSTREAM_TERMINATED');
    expect(output).toContain('RUN_FINISHED');
  });

  it('fails closed when an incomplete SSE event exceeds the framing limit', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      'data: ' + 'x'.repeat(1048577),
      { headers: { 'content-type': 'text/event-stream' } },
    )));
    const output = await (await POST(request())).text();
    expect(output).toContain('RUN_ERROR');
    expect(output).toContain('CHAT_STREAM_UPSTREAM_INTERRUPTED');
  });

  it('rejects a second terminal event instead of reporting an unambiguous success', async () => {
    const payload = 'data: {"type":"RUN_FINISHED"}\n\ndata: {"type":"RUN_ERROR"}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(payload, {
      headers: { 'content-type': 'text/event-stream' },
    })));
    await expect((await POST(request())).text()).rejects.toThrow(
      'AG-UI events received after terminal event',
    );
  });

  it('rejects message output after terminal completion', async () => {
    const payload = 'data: {"type":"RUN_FINISHED"}\n\ndata: {"type":"TEXT_MESSAGE_CONTENT","delta":"late"}\n\n';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(payload, {
      headers: { 'content-type': 'text/event-stream' },
    })));
    await expect((await POST(request())).text()).rejects.toThrow(
      'AG-UI events received after terminal event',
    );
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
