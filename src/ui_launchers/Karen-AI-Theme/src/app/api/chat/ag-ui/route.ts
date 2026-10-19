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
    return new NextResponse(upstream.body, { status: 200, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: 'AG-UI stream unavailable' }, { status: 502 });
  }
}
