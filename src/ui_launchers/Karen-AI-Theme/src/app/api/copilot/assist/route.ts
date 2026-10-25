import { NextRequest, NextResponse } from 'next/server';

import { proxyToBackend } from '../../_lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Compatibility transport for Karen's existing Copilot assistant.
 *
 * The backend owns authentication, tenant isolation, execution and idempotency.
 * Do not deduplicate on browser-supplied user/session/message fields: different
 * actors can supply the same values, so a module-global cache can leak results.
 * This is an execution POST, so automatic retries could also duplicate work.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  return proxyToBackend(request, '/api/copilot/assist', {
    longTimeout: true,
    retryAttempts: 1,
    retryOnStatusCodes: [],
    followRedirects: false,
  });
}
