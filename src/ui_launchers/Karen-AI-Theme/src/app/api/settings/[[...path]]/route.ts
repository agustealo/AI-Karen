import { NextRequest } from 'next/server';

import { proxyToBackend } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function getBackendPath(request: NextRequest) {
  const url = new URL(request.url);
  const apiPrefix = '/api/settings';
  const pathname = url.pathname;
  
  const index = pathname.indexOf(apiPrefix);
  if (index === -1) return '/api/settings';
  
  const subPath = pathname.substring(index + apiPrefix.length);
  return `/api/settings${subPath}`;
}

export async function GET(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    longTimeout: true,
    retryAttempts: 3,
    retryDelayMs: 250,
    retryOnStatusCodes: [500, 502, 503, 504],
  });
}

export async function PUT(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    longTimeout: true,
    retryAttempts: 3,
    retryDelayMs: 250,
    retryOnStatusCodes: [500, 502, 503, 504],
  });
}

export async function POST(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    longTimeout: true,
    retryAttempts: 3,
    retryDelayMs: 250,
    retryOnStatusCodes: [500, 502, 503, 504],
  });
}

export async function DELETE(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    longTimeout: true,
    retryAttempts: 3,
    retryDelayMs: 250,
    retryOnStatusCodes: [500, 502, 503, 504],
  });
}
