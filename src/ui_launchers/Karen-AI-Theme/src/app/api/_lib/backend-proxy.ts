import { NextRequest, NextResponse } from 'next/server';
import { existsSync, readFileSync } from 'node:fs';

const EXPLICIT_BACKEND_URL =
  process.env.KAREN_BACKEND_URL || process.env.BACKEND_URL || '';

const runningInContainer = (() => {
  if (process.env.KAREN_DOCKER === 'true' || process.env.IS_DOCKER === 'true') {
    return true;
  }
  if (process.env.container?.toLowerCase() === 'docker') {
    return true;
  }
  try {
    if (existsSync('/.dockerenv')) {
      return true;
    }
  } catch {
    // Ignore filesystem detection failures and fall through to other heuristics.
  }
  try {
    const cgroup = readFileSync('/proc/1/cgroup', 'utf8');
    if (cgroup.includes('docker') || cgroup.includes('containerd')) {
      return true;
    }
  } catch {
    // Ignore cgroup detection failures.
  }
  return false;
})();

const IS_DOCKER =
  process.env.KAREN_DOCKER === 'true' ||
  process.env.IS_DOCKER === 'true' ||
  process.env.HOSTNAME?.includes('api') ||
  process.env.HOSTNAME?.includes('web') ||
  runningInContainer;

// Explicit deployment configuration is authoritative. Never silently rewrite an
// operator-selected backend hostname based on container heuristics (which may
// also be true in hosted serverless environments).
const DEFAULT_BACKEND_URL =
  EXPLICIT_BACKEND_URL || (IS_DOCKER ? 'http://api:8000' : 'http://localhost:8000');

const DEFAULT_TIMEOUT_MS = Number.parseInt(
  process.env.NEXT_PUBLIC_API_PROXY_TIMEOUT_MS || '30000',
  10,
);
const LONG_TIMEOUT_MS = Number.parseInt(
  process.env.NEXT_PUBLIC_API_PROXY_LONG_TIMEOUT_MS || '120000',
  10,
);
const RETRYABLE_PROXY_ERROR_CODES = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'EPIPE',
  'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_SOCKET',
]);

function getBackendBaseUrl(): string {
  return DEFAULT_BACKEND_URL.replace(/\/$/, '');
}

function normalizeForwardedProto(value: string | null): 'http' | 'https' | null {
  const candidate = (value || '').trim().toLowerCase();
  if (candidate === 'http' || candidate === 'https') {
    return candidate;
  }
  return null;
}

function sanitizeHeaders(headers: Headers, backendBaseUrl: string): Headers {
  const nextHeaders = new Headers();

  headers.forEach((value, key) => {
    const k = key.toLowerCase();
    const skipHeaders = [
      'host',
      'content-length',
      'content-encoding',
      'connection',
      'keep-alive',
      'proxy-authenticate',
      'proxy-authorization',
      'te',
      'trailers',
      'transfer-encoding',
      'upgrade',
      // Forwarded scheme is normalized below. In production the canonical
      // server.mjs ingress overwrites it before Next handles the request.
      'x-forwarded-proto',
      // Vercel's deployment-authorization tokens are for the frontend ingress
      // only. They must never traverse Karen's authenticated API proxy.
      'x-vercel-protection-bypass',
      'x-vercel-trusted-oidc-idp-token',
      'x-vercel-oidc-token',
    ];

    if (!skipHeaders.includes(k)) {
      nextHeaders.set(key, value);
    }
  });

  const auth = headers.get('authorization');
  if (auth) nextHeaders.set('Authorization', auth);

  const cookie = headers.get('cookie');
  if (cookie) nextHeaders.set('Cookie', cookie);

  const backendHost = new URL(backendBaseUrl).host;
  nextHeaders.set('x-forwarded-host', headers.get('host') || backendHost);

  const forwardedProto = normalizeForwardedProto(headers.get('x-forwarded-proto'));
  if (forwardedProto) {
    nextHeaders.set('x-forwarded-proto', forwardedProto);
  }

  return nextHeaders;
}

export { getBackendBaseUrl, normalizeForwardedProto, sanitizeHeaders };

async function buildInit(
  request: NextRequest,
  backendBaseUrl: string,
  timeoutMs: number,
  overrideBody?: string,
): Promise<RequestInit> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  const body =
    request.method === 'GET' || request.method === 'HEAD' ? undefined : overrideBody;

  const init: RequestInit & { __timeout?: ReturnType<typeof setTimeout> } = {
    method: request.method,
    headers: sanitizeHeaders(request.headers, backendBaseUrl),
    body,
    cache: 'no-store',
    redirect: 'manual',
    signal: controller.signal,
    // @ts-expect-error Node/undici extension supported in Next runtime.
    duplex: body ? 'half' : undefined,
    next: { revalidate: 0 },
  };

  init.__timeout = timeout;
  return init;
}

function getTimeoutHandle(init: RequestInit): ReturnType<typeof setTimeout> | undefined {
  return (init as RequestInit & { __timeout?: ReturnType<typeof setTimeout> }).__timeout;
}

function clearInitTimeout(init: RequestInit): void {
  const timeout = getTimeoutHandle(init);
  if (timeout) {
    clearTimeout(timeout);
  }
}

function isRetryableProxyError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }

  if (error.name === 'AbortError') {
    return true;
  }

  const errorWithCode = error as Error & { code?: string; cause?: { code?: string } };
  const code = errorWithCode.code || errorWithCode.cause?.code;
  return Boolean(code && RETRYABLE_PROXY_ERROR_CODES.has(code));
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export async function proxyToBackend(
  request: NextRequest,
  upstreamPath: string,
  options?: {
    longTimeout?: boolean;
    retryAttempts?: number;
    retryDelayMs?: number;
    rawBody?: string;
    retryOnStatusCodes?: number[];
    // Disable for mutating execution endpoints to prevent replaying a POST.
    followRedirects?: boolean;
  },
): Promise<NextResponse> {
  const backendBaseUrl = getBackendBaseUrl();
  const timeoutMs = options?.longTimeout ? LONG_TIMEOUT_MS : DEFAULT_TIMEOUT_MS;
  // Only safe read methods may be retried or followed through redirects.
  // A transport failure/502 does not establish that a mutating POST failed
  // before persistence or execution. A second attempt could duplicate work.
  const safeRead = request.method === 'GET' || request.method === 'HEAD';
  const retryAttempts = safeRead ? Math.max(1, options?.retryAttempts ?? 2) : 1;
  const retryDelayMs = Math.max(0, options?.retryDelayMs ?? 250);
  const retryOnStatusCodes = new Set(options?.retryOnStatusCodes ?? [502]);
  const followRedirects = safeRead && (options?.followRedirects ?? true);
  const upstreamUrl = `${backendBaseUrl}${upstreamPath}${request.nextUrl.search}`;

  // Read the body once to avoid "Body has already been read" error on retries/redirects.
  // This is passed to buildInit to ensure it's reused.
  const capturedBody =
    options?.rawBody ??
    (request.method === 'GET' || request.method === 'HEAD'
      ? undefined
      : await request.text());

  let init = await buildInit(request, backendBaseUrl, timeoutMs, capturedBody);

  try {
    let upstream: Response | undefined;
    let lastError: unknown;

    for (let attempt = 1; attempt <= retryAttempts; attempt += 1) {
      try {
        upstream = await fetch(upstreamUrl, init);
        const shouldRetryStatus =
          retryOnStatusCodes.has(upstream.status) && attempt < retryAttempts;

        if (shouldRetryStatus) {
          clearInitTimeout(init);
          await sleep(retryDelayMs * attempt);
          init = await buildInit(request, backendBaseUrl, timeoutMs, capturedBody);
          continue;
        }

        lastError = undefined;
        break;
      } catch (error) {
        clearInitTimeout(init);
        lastError = error;

        const canRetry = isRetryableProxyError(error) && attempt < retryAttempts;
        if (!canRetry) {
          throw error;
        }

        await sleep(retryDelayMs * attempt);
        init = await buildInit(request, backendBaseUrl, timeoutMs, capturedBody);
      }
    }

    if (!upstream) {
      throw lastError instanceof Error ? lastError : new Error('Unknown proxy error');
    }

    // Follow redirects server-side to prevent internal Docker hostnames
    // (e.g. http://api:8000) from leaking to the browser via Location headers.
    const MAX_REDIRECTS = 5;
    let redirectCount = 0;
    while (
      followRedirects &&
      upstream.status >= 300 &&
      upstream.status < 400 &&
      upstream.headers.has('location') &&
      redirectCount < MAX_REDIRECTS
    ) {
      redirectCount += 1;
      const locationHeader = upstream.headers.get('location')!;

      // Resolve the redirect URL. If it's absolute with the backend host,
      // keep it as-is (we're server-side and can resolve Docker names).
      // If it's relative, resolve against the current upstream URL.
      let redirectUrl: string;
      try {
        const parsed = new URL(locationHeader);
        // Rewrite to use our known backend base to avoid stale Host headers
        redirectUrl = `${backendBaseUrl}${parsed.pathname}${parsed.search}`;
      } catch {
        // Relative URL – resolve against the backend base
        redirectUrl = `${backendBaseUrl}${locationHeader}`;
      }

      const redirectInit = await buildInit(
        request,
        backendBaseUrl,
        timeoutMs,
        capturedBody,
      );
      upstream = await fetch(redirectUrl, redirectInit);
      clearInitTimeout(redirectInit);
    }

    const responseBody = await upstream.text();
    const headers = new Headers(upstream.headers);
    clearInitTimeout(init);

    headers.delete('content-encoding');
    headers.delete('content-length');
    headers.delete('transfer-encoding');
    headers.delete('connection');
    // Remove any stale Location headers that point to internal Docker hosts
    headers.delete('location');
    headers.set('cache-control', 'no-store');

    return new NextResponse(responseBody, {
      status: upstream.status,
      headers,
    });
  } catch (error) {
    clearInitTimeout(init);

    // Some fetch/TLS errors embed the full upstream URL, including secrets.
    // Record structured error class only; never return or log raw causes.
    console.error('[BackendProxy] canonical_upstream_unavailable', {
      method: request.method,
      upstream_path: upstreamPath,
      error_type: error instanceof Error ? error.name : 'UnknownError',
    });

    return NextResponse.json(
      {
        detail: 'Canonical backend is unavailable.',
        error: 'Backend connection failed',
        error_code: 'BACKEND_UPSTREAM_UNAVAILABLE',
      },
      { status: 502, headers: { 'cache-control': 'no-store' } },
    );
  }
}
