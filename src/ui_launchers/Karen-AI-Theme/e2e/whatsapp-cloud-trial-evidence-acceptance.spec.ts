import { createHash } from 'node:crypto';
import { expect, test } from '@playwright/test';

import { signInApprovedKaren } from './fixtures/approved-karen-login';
import { verifyWhatsAppAcceptanceRevision } from './fixtures/whatsapp-acceptance-deployment';

/**
 * KWA-01C6C2C1: opt-in, operator-observed, real deployed ledger inspection.
 *
 * No fixtures, generated Meta traffic, screenshots, videos, or trace. Actual
 * provider-origin evidence must be collected independently outside the test.
 */
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

const required = process.env.KAREN_WHATSAPP_TRIAL_EVIDENCE_REQUIRED === 'true';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MESSAGE = /^wamid\.[A-Za-z0-9._+=/-]{1,250}$/;
const SHA = /^[0-9a-f]{64}$/;

function boundedText(name: string, pattern: RegExp): string {
  const value = process.env[name];
  if (!value || !pattern.test(value)) {
    // Never log the possibly private supplied value.
    throw new Error(`Approved ${name} operator evidence is required`);
  }
  return value;
}

test('KWA-01C6C2C1 real HTTPS host ledger matches operator-observed Meta outbound ID', async ({ page }) => {
  test.skip(!required, 'Requires approved exact-deployment real WhatsApp provider trial');

  const email = process.env.KAREN_UX_EMAIL;
  const password = process.env.KAREN_UX_PASSWORD;
  if (!email || !password) {
    throw new Error('Approved operator login credentials are required');
  }
  const connectionId = boundedText('KAREN_WHATSAPP_ACCEPTANCE_CONNECTION_ID', UUID);
  const inboundId = boundedText('KAREN_WHATSAPP_ACCEPTANCE_INBOUND_MESSAGE_ID', MESSAGE);
  const outboundId = boundedText('KAREN_WHATSAPP_ACCEPTANCE_OUTBOUND_MESSAGE_ID', MESSAGE);
  const expectedState = process.env.KAREN_WHATSAPP_TRIAL_REQUIRED_RECEIPT;
  if (expectedState !== 'delivered' && expectedState !== 'read') {
    throw new Error('Operator must explicitly require delivered or read receipt evidence');
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await verifyWhatsAppAcceptanceRevision(page.request);
  await signInApprovedKaren(page, email, password);

  const adminLink = page.getByRole('link', { name: 'Admin settings', exact: true });
  if (!(await adminLink.isVisible())) {
    await page.locator('[data-sidebar="trigger"]').first().click();
  }
  await expect(adminLink).toBeVisible();
  await adminLink.click();
  await expect(page).toHaveURL(/\/admin(?:[/?#]|$)/);
  await page.getByRole('tab', { name: 'WhatsApp Cloud', exact: true }).click();

  // Scope to the actual connection returned by the live tenant operator API,
  // never use the supplied ID to invent or locally add a connection.
  const connectionLabel = page.getByText(connectionId, { exact: true });
  await expect(connectionLabel).toBeVisible();
  const card = connectionLabel.locator('xpath=../..');
  const inspection = card.getByRole('region', { name: 'WhatsApp trial evidence inspection' });
  await expect(inspection).toBeVisible();
  await inspection.getByLabel('Inbound WhatsApp message ID').fill(inboundId);

  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname.endsWith('/trial-evidence') && response.request().method() === 'POST';
  }, { timeout: 30_000 });
  await inspection.getByRole('button', { name: 'Inspect persisted evidence' }).click();
  const response = await responsePromise;
  expect(response.status(), 'Host persisted trial inspection must succeed').toBe(200);

  const raw = await response.json() as unknown;
  // Compare only sanitized shape and derived digests; raw response/IDs never
  // enter assertion messages, logs, screenshots or artifacts.
  const evidence = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown> : null;
  const outboundDigest = createHash('sha256').update(outboundId, 'utf8').digest('hex');
  const valid =
    evidence !== null &&
    evidence.evidence_basis === 'host_persisted_lineage_only' &&
    evidence.meta_origin_independently_verified === false &&
    evidence.consumer_certified === false &&
    evidence.inbox_status === 'completed' &&
    ['sent', 'delivered', 'read'].includes(String(evidence.outbound_status)) &&
    typeof evidence.outbound_provider_message_sha256 === 'string' &&
    SHA.test(evidence.outbound_provider_message_sha256) &&
    evidence.outbound_provider_message_sha256 === outboundDigest &&
    Array.isArray(evidence.provider_receipt_states) &&
    evidence.provider_receipt_states.includes(expectedState) &&
    typeof evidence.correlation_id === 'string' &&
    UUID.test(evidence.correlation_id);
  expect(valid, 'Exact tenant, ChatRuntime stage, Meta ID fingerprint and receipt must match').toBe(true);
  await expect(inspection.getByText(/Host-persisted history only/)).toBeVisible();

  // A genuine operator-provided Meta ID is still input evidence, not an
  // independent provider attestation performed by this browser suite.
  expect(evidence?.consumer_certified).toBe(false);
});
