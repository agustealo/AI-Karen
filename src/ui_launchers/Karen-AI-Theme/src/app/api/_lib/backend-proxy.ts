import { NextRequest, NextResponse } from 'next/server';
import { existsSync, readFileSync } from 'node:fs';

const HOSTED_ON_VERCEL =
  process.env.VERCEL === '1' || Boolean(process.env.VERCEL_ENV);

// Hosted deployments must use the single canonical backend authority.
// BACKEND_URL remains a local compatibility alias, never a Vercel fallback.
const EXPLICIT_BACKEND_URL = HOSTED_ON_VERCEL
  ? (process.env.KAREN_BACKEND_URL || '')
  : (process.env.KAREN_BACKEND_URL || process.env.BACKEND_URL || '');

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

export type BackendTargetStatus =
  | 'configured'
  | 'missing'
  | 'invalid'
  | 'local_only'
  | 'insecure';

/**
 * Vercel is a distinct network from local Docker. An absent or Docker-only
 * backend URL is a deployment configuration failure, not a local fallback.
 */
function getBackendTargetStatus(): BackendTargetStatus {
  if (!HOSTED_ON_VERCEL) return 'configured';
  if (!EXPLICIT_BACKEND_URL.trim()) return 'missing';
  try {
    const target = new URL(EXPLICIT_BACKEND_URL);
    if (
      !['http:', 'https:'].includes(target.protocol) ||
      !target.hostname ||
      target.username || target.password ||
      (target.pathname !== '/' && target.pathname !== '') ||
      target.search || target.hash
    ) return 'invalid';
    const scope = backendTargetScope(EXPLICIT_BACKEND_URL);
    if (scope === 'loopback' || scope === 'docker_only') return 'local_only';
    if (scope === 'invalid') return 'invalid';
    if (scope === 'public_or_routed' && target.protocol !== 'https:') {
      return 'insecure';
    }
    return 'configured';
  } catch {
    return 'invalid';
  }
}

function getBackendBaseUrl(): string {
  if (getBackendTargetStatus() !== 'configured') {
    throw new Error('Canonical backend target is not configured for this deployment');
  }
  return DEFAULT_BACKEND_URL.replace(/\/$/, '');
}

/**
 * Diagnose connectivity without logging the operator-configured host, port,
 * path, username, password, DNS result or secret. Vercel's sensitive env vars
 * are intentionally unavailable to ordinary log readers.
 */
function backendTargetScope(baseUrl: string): string {
  try {
    const host = new URL(baseUrl).hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (/^(?:localhost|0\.0\.0\.0|127(?:\.\d{1,3}){3}|::1)$/.test(host)) {
      return 'loopback';
    }
    if (host === 'api' || host === 'host.docker.internal' || host.endsWith('.docker.internal')) {
      return 'docker_only';
    }
    if (/^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/.test(host)) {
      return 'private_ip';
    }
    if (host.endsWith('.internal') || host.endsWith('.local') || !host.includes('.')) {
      return 'private_dns';
    }
    return 'public_or_routed';
  } catch {
    return 'invalid';
  }
}

function safeCauseCode(error: unknown): string {
  if (!(error instanceof Error)) return 'UNKNOWN';
  const cause = (error as Error & { cause?: unknown }).cause;
  const code = cause && typeof cause === 'object' && 'code' in cause
    ? (cause as { code?: unknown }).code : undefined;
  const supported = new Set([
    'ECONNREFUSED', 'ECONNRESET', 'ENOTFOUND', 'EAI_AGAIN', 'ETIMEDOUT',
    'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_SOCKET', 'CERT_HAS_EXPIRED',
    'UNABLE_TO_VERIFY_LEAF_SIGNATURE', 'DEPTH_ZERO_SELF_SIGNED_CERT',
  ]);
  return typeof code === 'string' && supported.has(code) ? code : 'UNKNOWN';
}

function normalizeForwardedProto(value: string | null): 'http' | 'https' | null {
  const candidate = (value || '').trim().toLowerCase();
  if (candidate === 'http' || candidate === 'https') {
    return candidate;
  }
  return null;
}

function sanitizeBackendCookies(rawCookies: string): string {
  // Keep Karen's app session while stripping Vercel's *frontend ingress*
  // authorization. A backend API never needs a deployment-bypass credential.
  return rawCookies.split(';').map(cookie => cookie.trim()).filter(cookie => {
    const eq = cookie.indexOf('=');
    if (eq <= 0) return false;
    const name = cookie.slice(0, eq).trim().toLowerCase();
    return name !== '_vercel_jwt' &&
      name !== '__vercel_protection_bypass';
  }).join('; ');
}

function sanitizeHeaders(headers: Headers, backendBaseUrl: string): Headers {
  const nextHeaders = new Headers();

  headers.forEach((value, key) => {
    const k = key.toLowerCase();
    const skipHeaders = [
      'host',
      'cookie',
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
      'x-vercel-set-bypass-cookie',
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
  if (cookie) {
    const appCookies = sanitizeBackendCookies(cookie);
    if (appCookies) nextHeaders.set('Cookie', appCookies);
  }

  const backendHost = new URL(backendBaseUrl).host;
  nextHeaders.set('x-forwarded-host', headers.get('host') || backendHost);

  const forwardedProto = normalizeForwardedProto(headers.get('x-forwarded-proto'));
  if (forwardedProto) {
    nextHeaders.set('x-forwarded-proto', forwardedProto);
  }

  return nextHeaders;
}

export { getBackendBaseUrl, getBackendTargetStatus, normalizeForwardedProto, sanitizeHeaders };

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
  const targetStatus = getBackendTargetStatus();
  if (targetStatus !== 'configured') {
    console.error('[BackendProxy] canonical_backend_configuration_invalid', {
      target_status: targetStatus,
    });
    return NextResponse.json(
      {
        detail: 'Canonical backend connection is not configured for this deployment.',
        error_code: 'BACKEND_TARGET_NOT_CONFIGURED',
      },
      { status: 503, headers: { 'cache-control': 'no-store' } },
    );
  }
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

      // Never reinterpret an external Location as a path on Karen's API.
      // Follow only redirects that resolve to the same canonical origin.
      let redirectUrl: string;
      try {
        const parsed = new URL(locationHeader, upstreamUrl);
        if (parsed.origin !== new URL(backendBaseUrl).origin ||
            parsed.username || parsed.password) {
          throw new Error('Backend redirect crossed the canonical origin');
        }
        redirectUrl = parsed.toString();
      } catch {
        // No credential-bearing request is sent to another origin or to a
        // rewritten backend path derived from an external redirect.
        return NextResponse.json(
          { detail: 'Backend redirect rejected.', error_code: 'BACKEND_REDIRECT_REJECTED' },
          { status: 502, headers: { 'cache-control': 'no-store' } },
        );
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
      cause_code: safeCauseCode(error),
      target_scope: backendTargetScope(backendBaseUrl),
      configuration_source: EXPLICIT_BACKEND_URL ? 'explicit' : 'default',
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
