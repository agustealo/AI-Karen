import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '../_lib/backend-proxy';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const NO_STORE = { 'cache-control': 'no-store' };

function notReady(): NextResponse {
  return NextResponse.json(
    { status: 'initializing', backend_ready: false },
    { status: 503, headers: NO_STORE },
  );
}

/**
 * Consumer readiness follows the canonical FastAPI /ready authority.
 *
 * The backend's /api/health intentionally returns HTTP 200 for degraded
 * optional providers/extensions. That is useful observability but is NOT proof
 * that required PostgreSQL-backed authentication, conversation persistence
 * and tenant-owned state are ready for an interactive consumer session.
 *
 * Never manufacture a ready response based only on an HTTP 200. The backend
 * must explicitly attest to configuration and database readiness.
 */
export const GET = async (request: Request): Promise<NextResponse> => {
  try {
    const nextRequest = new NextRequest(request.url, {
      method: 'GET',
      headers: request.headers,
    });
    const response = await proxyToBackend(nextRequest, '/ready', {
      followRedirects: false,
    });

    if (response.status === 503) return notReady();
    if (response.status !== 200) {
      response.headers.set('cache-control', 'no-store');
      return response;
    }

    const payload: unknown = await response.json();
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return notReady();
    }
    const readiness = payload as Record<string, unknown>;
    const components = readiness.components;
    if (
      readiness.ready !== true ||
      readiness.status !== 'ready' ||
      !components ||
      typeof components !== 'object' ||
      Array.isArray(components) ||
      (components as Record<string, unknown>).configuration !== 'ready' ||
      (components as Record<string, unknown>).database !== 'ready'
    ) {
      return notReady();
    }

    return NextResponse.json(
      { status: 'ok', backend_ready: true },
      { headers: NO_STORE },
    );
  } catch {
    return notReady();
  }
};
