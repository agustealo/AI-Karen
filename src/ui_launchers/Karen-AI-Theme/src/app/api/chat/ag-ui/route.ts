import { NextRequest, NextResponse } from 'next/server';
import { getBackendBaseUrl, sanitizeHeaders } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Proxies the optional AG-UI wire protocol to Karen's canonical backend. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const backendBaseUrl = getBackendBaseUrl();
  const headers = sanitizeHeaders(request.headers, backendBaseUrl);
  headers.set('Accept', 'text/event-stream');

  try {
    const upstream = await fetch(`${backendBaseUrl}/api/chat/ag-ui`, {
      method: 'POST',
      headers,
      body: await request.text(),
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
    });

    if (!upstream.ok) {
      return new NextResponse(await upstream.text(), {
        status: upstream.status,
        headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json' },
      });
    }
    if (!upstream.body || !upstream.headers.get('content-type')?.startsWith('text/event-stream')) {
      await upstream.body?.cancel();
      return NextResponse.json({ detail: 'Backend did not return an AG-UI event stream' }, { status: 502 });
    }
    const responseHeaders = new Headers({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    });
    for (const key of ['x-correlation-id', 'x-response-id']) {
      const value = upstream.headers.get(key);
      if (value) responseHeaders.set(key, value);
    }
    // AG-UI completion must be a fully framed RUN_FINISHED or RUN_ERROR.
    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    const encoder = new TextEncoder();
    let pending = '';
    let terminalSeen = false;
    let released = false;
    const release = () => {
      if (!released) {
        released = true;
        reader.releaseLock();
      }
    };

    // SSE data fields may span multiple lines and transport chunks.
    // Never infer terminal success from an incomplete or oversized record.
    const MAX_PENDING_EVENT_BYTES = 1048576;
    const inspect = (bytes: Uint8Array) => {
      pending += decoder.decode(bytes, { stream: true });
      if (pending.length > MAX_PENDING_EVENT_BYTES && !/\r?\n\r?\n/.test(pending)) {
        throw new Error('AG-UI event exceeded the maximum framing size');
      }
      const records = pending.split(/\r?\n\r?\n/);
      pending = records.pop() || '';
      for (const record of records) {
        if (record.length > MAX_PENDING_EVENT_BYTES) {
          throw new Error('AG-UI event exceeded the maximum framing size');
        }
        const dataLines = record.split(/\r?\n/)
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart());
        if (!dataLines.length) continue;
        try {
          const event = JSON.parse(dataLines.join('\n')) as { type?: string };
          if (event.type === 'RUN_FINISHED' || event.type === 'RUN_ERROR') {
            terminalSeen = true;
          }
        } catch {
          // Malformed SSE does not satisfy the terminal contract.
        }
      }
    };

    const fail = (
      controller: ReadableStreamDefaultController<Uint8Array>,
      code: 'CHAT_STREAM_UPSTREAM_TERMINATED' | 'CHAT_STREAM_UPSTREAM_INTERRUPTED',
    ) => {
      if (terminalSeen || request.signal.aborted) return;
      // Leading blank record separators keep a partial upstream frame from
      // swallowing the transport diagnostic.
      controller.enqueue(encoder.encode(
        `\n\ndata: ${JSON.stringify({
          type: 'RUN_ERROR',
          message: 'The backend stream ended before runtime completion.',
          code,
        })}\n\n`,
      ));
      terminalSeen = true;
    };

    const guardedStream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const { done, value } = await reader.read();
          if (done) {
            fail(controller, 'CHAT_STREAM_UPSTREAM_TERMINATED');
            controller.close();
            release();
            return;
          }
          if (value) {
            inspect(value);
            controller.enqueue(value);
          }
        } catch (error) {
          if (request.signal.aborted) {
            controller.error(error);
          } else {
            fail(controller, 'CHAT_STREAM_UPSTREAM_INTERRUPTED');
            controller.close();
          }
          release();
        }
      },
      async cancel(reason) {
        try {
          await reader.cancel(reason);
        } finally {
          release();
        }
      },
    });
    return new NextResponse(guardedStream, { status: 200, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: 'AG-UI stream unavailable' }, { status: 502 });
  }
}
