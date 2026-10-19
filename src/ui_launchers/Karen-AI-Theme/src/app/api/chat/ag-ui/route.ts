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
    // The AG-UI protocol has no [DONE] sentinel: a complete SSE record
    // carrying RUN_FINISHED or RUN_ERROR is required.
    const decoder = new TextDecoder();
    const encoder = new TextEncoder();
    let pending = '';
    let terminalSeen = false;
    const guardedStream = upstream.body.pipeThrough(
      new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          pending += decoder.decode(chunk, { stream: true });
          const records = pending.split(/\r?\n\r?\n/);
          pending = records.pop() || '';
          for (const record of records) {
            for (const line of record.split(/\r?\n/)) {
              if (!line.startsWith('data:')) continue;
              try {
                const event = JSON.parse(line.slice(5).trimStart()) as { type?: string };
                if (event.type === 'RUN_FINISHED' || event.type === 'RUN_ERROR') {
                  terminalSeen = true;
                }
              } catch {
                // Malformed frames cannot establish completion.
              }
            }
          }
          if (pending.length > 1048576) pending = pending.slice(-8192);
          controller.enqueue(chunk);
        },
        flush(controller) {
          if (!terminalSeen && !request.signal.aborted) {
            controller.enqueue(encoder.encode(
              '\n\ndata: {"type":"RUN_ERROR","message":"Backend stream ended before completion.","code":"CHAT_STREAM_UPSTREAM_TERMINATED"}\n\n',
            ));
          }
        },
      }),
    );
    return new NextResponse(guardedStream, { status: 200, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: 'AG-UI stream unavailable' }, { status: 502 });
  }
}
