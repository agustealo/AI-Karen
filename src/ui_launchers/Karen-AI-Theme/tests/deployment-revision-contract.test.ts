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
});
