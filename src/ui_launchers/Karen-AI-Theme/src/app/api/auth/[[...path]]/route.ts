import { NextRequest } from 'next/server';

import { proxyToBackend } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function getBackendPath(request: NextRequest): string {
  const url = new URL(request.url);
  const apiPrefix = '/api/auth';
  const index = url.pathname.indexOf(apiPrefix);

  if (index === -1) {
    return apiPrefix;
  }

  return `${apiPrefix}${url.pathname.substring(index + apiPrefix.length)}`;
}

export async function GET(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    retryAttempts: 3,
    retryDelayMs: 250,
    retryOnStatusCodes: [500, 502, 503, 504],
  });
}

// Authentication and account mutations must be sent exactly once. A missing
// receipt is not permission to replay a password, profile, or login operation.
export async function POST(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    retryAttempts: 1,
  });
}

// The canonical self-account endpoint is PUT /api/auth/me. Previously the
// browser proxy did not implement PUT, leaving profile and theme saves inert.
export async function PUT(request: NextRequest) {
  return proxyToBackend(request, getBackendPath(request), {
    retryAttempts: 1,
  });
}
