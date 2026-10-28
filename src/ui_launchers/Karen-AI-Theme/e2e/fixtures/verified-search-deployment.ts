import { expect, test as base } from '@playwright/test';

/**
 * Shared authenticated release fixture. For Vercel, sets only the exact-host
 * deployment-protection cookie. For signed Docker, validates the approved HTTPS
 * origin and sends no provider-bypass request. Does not intercept or mock API
 * responses, alter model output or persist browser authentication state.
 *
 * The bypass secret is never attached to general browser requests. In
 * particular, external citation links cannot receive it.
 */
export { expect };

export const test = base.extend<{ approvedDeploymentAccess: void }>({
  approvedDeploymentAccess: [
    async ({ context, baseURL }, use) => {
      if (process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED !== 'true' &&
          process.env.KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED !== 'true' &&
          process.env.KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED !== 'true') {
        await use();
        return;
      }

      const platform = process.env.KAREN_SEARCH_ACCEPTANCE_PLATFORM || 'vercel';
      const bypassSecret = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
      const approvedUrl = process.env.KAREN_BASE_URL;
      if (!baseURL || !approvedUrl || !['vercel', 'docker'].includes(platform)) {
        throw new Error('Missing approved search deployment URL or platform');
      }

      let approved: URL;
      let configured: URL;
      try {
        approved = new URL(approvedUrl);
        configured = new URL(baseURL);
      } catch {
        throw new Error('Approved search deployment origin is malformed');
      }
      const validOrigin = (url: URL): boolean =>
        url.protocol === 'https:' &&
        url.port === '' &&
        !url.username && !url.password &&
        url.pathname === '/' && !url.search && !url.hash;
      if (
        !validOrigin(approved) ||
        !validOrigin(configured) ||
        approved.origin !== configured.origin
      ) {
        throw new Error('Refusing authenticated search on an unapproved HTTPS origin');
      }

      if (platform === 'docker') {
        if (bypassSecret !== undefined) {
          throw new Error('Docker acceptance must not inherit a Vercel bypass secret');
        }
        // The protected host job independently verified signed running Docker
        // images before browser credentials became eligible for this job.
        await use();
        return;
      }
      const immutableHost = /^[a-z0-9][a-z0-9-]*\.vercel\.app$/;
      if (!bypassSecret || !immutableHost.test(approved.hostname)) {
        throw new Error('Missing reviewed Vercel preview or automation authorization');
      }

      // APIRequestContext and BrowserContext share the same cookie jar.
      // The request is never redirected and the secret is only sent to the
      // first-party immutable deployment origin.
      const response = await context.request.get(approved.origin, {
        headers: {
          'x-vercel-protection-bypass': bypassSecret,
          'x-vercel-set-bypass-cookie': 'true',
        },
        maxRedirects: 0,
        timeout: 20_000,
      });
      const destination = response.headers().location;
      if (destination && new URL(destination, approved.origin).origin !== approved.origin) {
        throw new Error('Protected preview redirected outside the verified deployment origin');
      }
      const cookies = await context.cookies(approved.origin);
      const sessionEstablished = cookies.some(
        (cookie) =>
          cookie.name === '_vercel_jwt' &&
          cookie.secure &&
          cookie.domain.replace(/^\./, '') === approved.hostname,
      );
      if (response.status() >= 400 || !sessionEstablished) {
        throw new Error('Vercel deployment authentication did not establish a scoped cookie');
      }

      await use();
    },
    { auto: true },
  ],
});
