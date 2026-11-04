import { NextRequest, NextResponse } from 'next/server';
import { getBackendBaseUrl, sanitizeHeaders } from '../../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Legacy streaming ingress remains a compatibility transport only.
 * Authentication, tenant authorization, model selection and persistence
 * belong to the canonical backend. An execution POST must be attempted once
 * against one configured target. A network exception cannot establish whether
 * the first attempt executed, so fail closed instead of replaying it.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  let backendBaseUrl: string;
  try {
    backendBaseUrl = getBackendBaseUrl();
  } catch {
    return NextResponse.json(
      {
        detail: 'Canonical backend connection is not configured for this deployment.',
        error_code: 'BACKEND_TARGET_NOT_CONFIGURED',
      },
      { status: 503, headers: { 'cache-control': 'no-store' } },
    );
  }

  try {
    const headers = sanitizeHeaders(request.headers, backendBaseUrl);
    headers.set('Accept', 'text/event-stream');
    const upstream = await fetch(`${backendBaseUrl}/api/copilot/assist/stream`, {
      method: 'POST',
      headers,
      body: await request.text(),
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
      // @ts-expect-error Node/undici accepts streamed request bodies.
      duplex: 'half',
    });

    // Never replay a POST after 3xx or forward an internal Location.
    if (upstream.status >= 300 && upstream.status < 400) {
      await upstream.body?.cancel().catch(() => undefined);
      return NextResponse.json(
        {
          detail: 'The canonical backend redirected a streaming request.',
          error_code: 'COPILOT_STREAM_UPSTREAM_REDIRECT',
        },
        { status: 502, headers: { 'cache-control': 'no-store' } },
      );
    }

    if (!upstream.ok) {
      await upstream.body?.cancel().catch(() => undefined);
      // The upstream error body may contain tokens, URLs or private messages.
      // Preserve the status but never log or reflect its untrusted body.
      return NextResponse.json(
        {
          detail: 'The canonical backend rejected the stream request.',
          error_code: 'COPILOT_STREAM_UPSTREAM_REJECTED',
        },
        { status: upstream.status, headers: { 'cache-control': 'no-store' } },
      );
    }

    if (!upstream.body ||
        !/^text\/event-stream(?:\s*;|\s*$)/i.test(
          upstream.headers.get('content-type') || '',
        )) {
      await upstream.body?.cancel().catch(() => undefined);
      return NextResponse.json(
        {
          detail: 'Canonical backend did not return an event stream.',
          error_code: 'COPILOT_STREAM_INVALID_CONTENT_TYPE',
        },
        { status: 502, headers: { 'cache-control': 'no-store' } },
      );
    }

    const responseHeaders = new Headers({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    });
    const correlationId = upstream.headers.get('x-correlation-id');
    if (correlationId) {
      responseHeaders.set('X-Correlation-Id', correlationId);
    }

    // Do not synthesize a model response, terminal event or persistence claim.
    // The canonical backend owns stream termination and runtime receipts.
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error('[CopilotStreamProxy] canonical_stream_unavailable', {
      error_type: error instanceof Error ? error.name : 'UnknownError',
    });
    return NextResponse.json(
      {
        detail: 'Canonical stream unavailable.',
        error_code: 'COPILOT_STREAM_UNAVAILABLE',
      },
      { status: 502, headers: { 'cache-control': 'no-store' } },
    );
  }
}
