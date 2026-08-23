import { NextRequest, NextResponse } from 'next/server';
import { getBackendBaseUrl, sanitizeHeaders } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function formatProxyError(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`;
  }
  if (typeof error === 'string') {
    return error;
  }
  if (typeof error === 'object' && error !== null) {
    const maybeName = (error as { name?: unknown }).name;
    const maybeMessage = (error as { message?: unknown }).message;
    const name = typeof maybeName === 'string' ? maybeName : 'UnknownError';
    const message =
      typeof maybeMessage === 'string' && maybeMessage.trim()
        ? maybeMessage
        : 'No message';
    return `${name}: ${message}`;
  }
  return String(error);
}

export async function POST(request: NextRequest) {
  const backendBaseUrl = getBackendBaseUrl();
  const primaryUpstreamUrl = `${backendBaseUrl}/api/chat/stream`;
  const fallbackUpstreamUrls = [
    'http://api:8000/api/chat/stream',
    'http://host.docker.internal:8000/api/chat/stream',
  ].filter((url) => url !== primaryUpstreamUrl);

  try {
    const rawBody = await request.text();
    const headers = sanitizeHeaders(request.headers, backendBaseUrl);

    const candidateUrls = [primaryUpstreamUrl, ...fallbackUpstreamUrls];
    let upstream: Response | null = null;
    let lastProxyError: unknown = null;
    let attemptedUrl = primaryUpstreamUrl;

    for (const upstreamUrl of candidateUrls) {
      attemptedUrl = upstreamUrl;
      try {
        upstream = await fetch(upstreamUrl, {
          method: 'POST',
          headers,
          body: rawBody,
          cache: 'no-store',
          redirect: 'manual',
          signal: request.signal,
          // @ts-expect-error Node/undici extension supported in Next runtime.
          duplex: 'half',
        });
        break;
      } catch (proxyError) {
        lastProxyError = proxyError;
      }
    }

    if (!upstream) {
      throw (
        lastProxyError instanceof Error
          ? new Error(
              `All upstream targets failed. Last target: ${attemptedUrl}. Last error: ${lastProxyError.message}`,
            )
          : new Error(`All upstream targets failed. Last target: ${attemptedUrl}.`)
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

    if (!upstream.body) {
      return new NextResponse('No response body from upstream', { status: 502 });
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

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    const formattedError = formatProxyError(error);
    console.error(
      `[StreamProxy] Failed to proxy stream request: ${formattedError}`,
    );
    const detail =
      error instanceof Error && error.name === 'AbortError'
        ? 'Stream request was cancelled'
        : error instanceof Error
          ? error.message
          : 'Unknown proxy error';

    return NextResponse.json(
      { detail: 'Failed to proxy stream to backend', error: detail },
      { status: 502 },
    );
  }
}
