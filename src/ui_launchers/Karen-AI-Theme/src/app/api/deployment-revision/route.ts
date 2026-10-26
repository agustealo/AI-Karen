import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * Read-only deployment provenance for release acceptance.
 * The value must be injected from the deployed build/revision, not provided
 * by a browser request, user metadata, or a runtime model response.
 */
export function GET() {
  const revision = process.env.VERCEL_GIT_COMMIT_SHA || process.env.KAREN_DEPLOYED_COMMIT_SHA;
  if (!revision || !/^[a-f0-9]{40}$/.test(revision)) {
    return NextResponse.json(
      { status: 'unavailable', reason: 'Deployment revision is not configured' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  return NextResponse.json(
    { status: 'ok', revision },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
