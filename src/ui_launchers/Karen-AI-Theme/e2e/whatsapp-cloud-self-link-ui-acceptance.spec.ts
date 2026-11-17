import { expect, test } from '@playwright/test';

import { signInApprovedKaren } from './fixtures/approved-karen-login';
import { verifyWhatsAppAcceptanceRevision } from './fixtures/whatsapp-acceptance-deployment';

/**
 * KWA-01C6C2B2: actual signed-in consumer navigation and zero-secret observer.
 *
 * No mocked backend, generated challenge, Meta command, provider data,
 * screenshots, trace or video. A passing view does not prove sender linking.
 */
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

const required = process.env.KAREN_WHATSAPP_SELF_LINK_UI_ACCEPTANCE_REQUIRED === 'true';
const writePath = '/api/channels/identity/whatsapp/';

for (const width of [390, 768, 1440]) {
  test(`KWA-01C6C2B2: consumer Channels self-link at ${width}px`, async ({ page }) => {
    test.skip(!required, 'Requires approved exact-revision HTTPS consumer acceptance');

    const email = process.env.KAREN_UX_EMAIL;
    const password = process.env.KAREN_UX_PASSWORD;
    if (!email || !password) {
      throw new Error('Approved verified Karen test-user credentials are required');
    }

    await page.setViewportSize({ width, height: 900 });
    await verifyWhatsAppAcceptanceRevision(page.request);
    await signInApprovedKaren(page, email, password);

    let mutatingRequests = 0;
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith(writePath) &&
          !['GET', 'HEAD'].includes(request.method())) {
        mutatingRequests += 1;
      }
    });

    const settings = page.getByRole('button', { name: 'Application Settings', exact: true });
    if (!(await settings.isVisible())) {
      await page.locator('[data-sidebar="trigger"]').first().click();
    }
    await expect(settings).toBeVisible();
    await settings.click();

    await expect(page.getByRole('heading', { name: 'Application Settings' })).toBeVisible();
    await page.getByRole('tab', { name: 'Personal', exact: true }).click();
    const sectionNavigation = page.getByRole('navigation', { name: 'Personal settings sections' });
    await sectionNavigation.getByRole('button', { name: 'Channels', exact: true }).click();

    const panel = page.getByRole('region', { name: 'WhatsApp Cloud account linking' });
    await expect(panel).toBeVisible();
    await expect(panel.getByText('Link your WhatsApp Cloud sender')).toBeVisible();
    const input = panel.getByLabel('Operator-provided connection ID');
    await expect(input).toBeVisible();
    const button = panel.getByRole('button', { name: 'Request one-time link command' });
    await expect(button).toBeDisabled();

    await input.fill('not-a-valid-connection');
    await expect(button).toBeDisabled();
    await expect(panel.getByText(/No provider delivery or linked status is asserted/))
      .toBeVisible();
    await expect(panel.getByLabel('One-time WhatsApp link command')).toHaveCount(0);

    // Merely viewing settings must never mint a bearer proof, select an
    // external provider, send a message, or create a client-side "linked" state.
    expect(mutatingRequests).toBe(0);
  });
}
