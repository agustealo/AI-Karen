import { NextRequest, NextResponse } from 'next/server';
import { getBackendBaseUrl, sanitizeHeaders } from '../../_lib/backend-proxy';
import { observeChatSseBody } from '../../_lib/sse-stream-integrity';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  // The canonical backend proxy configuration is the only authority for
  // streaming. Never replay an execution POST to an alternative host after a
  // transport error or 404. The outcome of the first request may be unknown,
  // and forwarding authorization to a secondary host violates isolation.
  const backendBaseUrl = getBackendBaseUrl();

  try {
    const rawBody = await request.text();
    const headers = sanitizeHeaders(request.headers, backendBaseUrl);
    const upstream = await fetch(`${backendBaseUrl}/api/chat/stream`, {
      method: 'POST',
      headers,
      body: rawBody,
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
      // @ts-expect-error Node/undici extension supported in Next runtime.
      duplex: 'half',
    });

    // An upstream redirect is never license to replay a chat execution POST.
    // Never expose internal backend Location headers to the browser.
    if (upstream.status >= 300 && upstream.status < 400) {
      await upstream.body?.cancel().catch(() => undefined);
      return NextResponse.json(
        {
          detail: 'The canonical chat backend redirected a streaming request.',
          error_code: 'CHAT_STREAM_UPSTREAM_REDIRECT',
        },
        { status: 502, headers: { 'cache-control': 'no-store' } },
      );
    }

    if (!upstream.ok) {
      const errorBody = await upstream.text().catch(() => 'Upstream error');
      console.error(
        `[StreamProxy] Upstream returned ${upstream.status}: ${errorBody.slice(0, 200)}`,
      );
      return new NextResponse(errorBody, {
        status: upstream.status,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Never relabel an HTTP 200 JSON/HTML diagnostic as successful SSE.
    // Auth gateways and old upstreams can respond 200 without chat events.
    const upstreamContentType = upstream.headers.get('content-type') || '';
    const upstreamCorrelationId = upstream.headers.get('x-correlation-id') || '';
    if (!/^text\/event-stream(?:\s*;|\s*$)/i.test(upstreamContentType)) {
      console.error('[ChatStreamProxy] unexpected_upstream_content_type', {
        correlation_id: upstreamCorrelationId,
        content_type: upstreamContentType.slice(0, 100),
      });
      await upstream.body?.cancel().catch(() => undefined);
      return NextResponse.json(
        {
          detail: 'The backend did not return a chat event stream.',
          error_code: 'CHAT_STREAM_UPSTREAM_NOT_SSE',
          correlation_id: upstreamCorrelationId || undefined,
        },
        { status: 502 },
      );
    }

    if (!upstream.body) {
      return NextResponse.json(
        {
          detail: 'The backend returned no chat stream body.',
          error_code: 'CHAT_STREAM_UPSTREAM_NO_BODY',
          correlation_id: upstreamCorrelationId || undefined,
        },
        { status: 502 },
      );
    }

    const responseHeaders = new Headers();
    responseHeaders.set('Content-Type', 'text/event-stream');
    responseHeaders.set('Cache-Control', 'no-cache');
    responseHeaders.set('Connection', 'keep-alive');
    responseHeaders.set('X-Accel-Buffering', 'no');

    const correlationId = upstream.headers.get('x-correlation-id');
    if (correlationId) {
      responseHeaders.set('X-Correlation-Id', correlationId);
    }

    const responseId = upstream.headers.get('x-response-id');
    if (responseId) {
      responseHeaders.set('X-Response-Id', responseId);
    }

    return new NextResponse(
      observeChatSseBody(
        upstream.body,
        upstreamCorrelationId,
        request.signal,
      ),
      {
        status: upstream.status,
        headers: responseHeaders,
      },
    );
  } catch (error) {
    // Do not log remote URLs, credentials, body text or raw fetch causes.
    console.error('[StreamProxy] canonical_stream_unavailable', {
      error_type: error instanceof Error ? error.name : 'UnknownError',
    });
    const wasAborted = request.signal.aborted ||
      (error instanceof Error && error.name === 'AbortError');
    return NextResponse.json(
      {
        detail: wasAborted
          ? 'Chat stream request was cancelled.'
          : 'Canonical chat backend is unavailable.',
        error_code: wasAborted
          ? 'CHAT_STREAM_CANCELLED'
          : 'CHAT_STREAM_BACKEND_UNAVAILABLE',
      },
      { status: 502, headers: { 'cache-control': 'no-store' } },
    );
  }
}
