import { afterEach, describe, expect, it, vi } from 'vitest';
import { GET } from '../src/app/api/deployment-revision/route';

const originalVercel = process.env.VERCEL_GIT_COMMIT_SHA;
const originalKaren = process.env.KAREN_DEPLOYED_COMMIT_SHA;

afterEach(() => {
  if (originalVercel === undefined) delete process.env.VERCEL_GIT_COMMIT_SHA;
  else process.env.VERCEL_GIT_COMMIT_SHA = originalVercel;
  if (originalKaren === undefined) delete process.env.KAREN_DEPLOYED_COMMIT_SHA;
  else process.env.KAREN_DEPLOYED_COMMIT_SHA = originalKaren;
  vi.restoreAllMocks();
});

describe('deployment revision release contract', () => {
  it('fails closed when no deployed revision is configured', async () => {
    delete process.env.VERCEL_GIT_COMMIT_SHA;
    delete process.env.KAREN_DEPLOYED_COMMIT_SHA;
    const response = GET();
    expect(response.status).toBe(503);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect((await response.json()).status).toBe('unavailable');
  });

  it('rejects malformed deployment revision metadata', async () => {
    delete process.env.VERCEL_GIT_COMMIT_SHA;
    process.env.KAREN_DEPLOYED_COMMIT_SHA = 'main';
    expect(GET().status).toBe(503);
  });

  it('reports the server-injected full revision without caching', async () => {
    delete process.env.VERCEL_GIT_COMMIT_SHA;
    const expected = 'a'.repeat(40);
    process.env.KAREN_DEPLOYED_COMMIT_SHA = expected;
    const response = GET();
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({ status: 'ok', revision: expected });
  });

  it('fails closed when revision sources disagree', async () => {
    process.env.VERCEL_GIT_COMMIT_SHA = 'a'.repeat(40);
    process.env.KAREN_DEPLOYED_COMMIT_SHA = 'b'.repeat(40);
    const response = GET();
    expect(response.status).toBe(503);
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('fails closed on a malformed platform revision even with a valid fallback', () => {
    process.env.VERCEL_GIT_COMMIT_SHA = 'main';
    process.env.KAREN_DEPLOYED_COMMIT_SHA = 'a'.repeat(40);
    expect(GET().status).toBe(503);
  });

  it('accepts equal verified-format platform and injected revisions', async () => {
    const expected = 'c'.repeat(40);
    process.env.VERCEL_GIT_COMMIT_SHA = expected;
    process.env.KAREN_DEPLOYED_COMMIT_SHA = expected;
    const response = GET();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok', revision: expected });
  });

});
