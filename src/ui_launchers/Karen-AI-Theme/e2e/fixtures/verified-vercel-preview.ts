import { expect, test as base } from '@playwright/test';

/**
 * Authenticated preview fixture. Only prepares Vercel's deployment-protection
 * cookie on the exact reviewed origin. Does not intercept or mock application
 * responses, alter model output, or persist browser authentication state.
 *
 * The bypass secret is never attached to general browser requests. In
 * particular, external citation links cannot receive it.
 */
export { expect };

export const test = base.extend<{ approvedPreviewAccess: void }>({
  approvedPreviewAccess: [
    async ({ context, baseURL }, use) => {
      if (process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED !== 'true') {
        await use();
        return;
      }

      const bypassSecret = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
      const approvedUrl = process.env.KAREN_BASE_URL;
      if (!baseURL || !approvedUrl || !bypassSecret) {
        throw new Error('Missing reviewed preview URL or protected automation authorization');
      }

      const approved = new URL(approvedUrl);
      const configured = new URL(baseURL);
      const immutableHost = /^[a-z0-9][a-z0-9-]*\.vercel\.app$/;
      if (
        approved.protocol !== 'https:' ||
        approved.username || approved.password ||
        approved.pathname !== '/' || approved.search || approved.hash ||
        !immutableHost.test(approved.hostname) ||
        configured.origin !== approved.origin ||
        configured.pathname !== '/' || configured.search || configured.hash
      ) {
        throw new Error('Refusing deployment protection bypass on an unapproved origin');
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
