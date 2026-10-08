import { NextRequest } from 'next/server';
import { proxyToBackend } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const proxied = await proxyToBackend(request, '/api/extensions/list', {
    longTimeout: true,
    retryAttempts: 4,
    retryDelayMs: 300,
    retryOnStatusCodes: [502, 503, 504],
  });

  // Preserve backend availability and authorization errors. Returning an
  // empty 200 here misreports outages as an uninstalled plugin catalog.
  return proxied;
}
