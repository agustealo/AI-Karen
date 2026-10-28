import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * Read-only deployment provenance for release acceptance.
 * The value must be injected from the deployed build/revision, not provided
 * by a browser request, user metadata, or a runtime model response.
 */
export function GET() {
  const platformRevision = process.env.VERCEL_GIT_COMMIT_SHA;
  const injectedRevision = process.env.KAREN_DEPLOYED_COMMIT_SHA;
  const revision = platformRevision || injectedRevision;
  const validSha = (value: string): boolean => /^[a-f0-9]{40}$/.test(value);

  // Never silently trust one claimed build identity over a conflicting or
  // malformed identity from another configured source.
  if (
    !revision ||
    !validSha(revision) ||
    (platformRevision && !validSha(platformRevision)) ||
    (injectedRevision && !validSha(injectedRevision)) ||
    (platformRevision && injectedRevision && platformRevision !== injectedRevision)
  ) {
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
