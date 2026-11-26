import { test, expect } from '@playwright/test';

const ARTIFACT_DIR = '/home/zeus/.gemini/antigravity/brain/6478df13-a684-44f2-8ada-aa42f4b9009f';

test('KLOCAL-CHAT: first-send, durable reload, follow-up, and responsive screenshots', async ({ page }) => {
  test.setTimeout(180_000);
  const baseUrl = process.env.KAREN_BASE_URL || 'http://localhost:8010';
  const email = process.env.KAREN_UX_EMAIL || 'admin@karen.ai';
  const password = process.env.KAREN_UX_PASSWORD || '!Password123';

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/login`);
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });

  const panel = page.getByTestId('persistent-karen-conversation');
  if (await page.getByRole('button', { name: 'Ask Karen', exact: true }).isVisible({ timeout: 3000 }).catch(() => false)) {
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  }
  await expect(panel).toHaveAttribute('aria-hidden', 'false');

  // Start a brand-new conversation cleanly
  const newBtn = page.getByRole('button', { name: 'Start a new conversation', exact: true })
    .or(panel.getByRole('button', { name: 'New conversation', exact: true }).first());
  if (await newBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await newBtn.click();
    await page.waitForTimeout(1500);
  }

  const composer = panel.getByTestId('karen-copilot-sdk-chat').locator('textarea').first();
  await expect(composer).toBeVisible({ timeout: 30_000 });

  // Turn 1: First send
  const msg1 = `KLOCAL-CHAT first turn ${Date.now()}: Hello Karen!`;
  const assistantLocator = panel.getByTestId('karen-copilot-assistant-message');
  const countBefore = await assistantLocator.count();
  await composer.fill(msg1);
  await composer.press('Enter');

  await expect.poll(() => assistantLocator.count(), { timeout: 90_000 }).toBeGreaterThan(countBefore);
  await expect.poll(async () => (await assistantLocator.last().innerText()).trim().length, { timeout: 90_000 }).toBeGreaterThan(5);
  // Wait briefly for stream completion & durable commit
  await page.waitForTimeout(2000);

  // Reload page to prove durable 200 history restoration (NO 409 recovery banner!)
  await page.reload();
  if (await page.getByRole('button', { name: 'Ask Karen', exact: true }).isVisible({ timeout: 3000 }).catch(() => false)) {
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  }
  await expect(panel.getByText(msg1, { exact: false })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('cannot faithfully restore in this chat yet', { exact: false })).toHaveCount(0);

  // Turn 2: Follow-up in the exact same restored conversation
  const composerAfterReload = panel.getByTestId('karen-copilot-sdk-chat').locator('textarea').first();
  await expect(composerAfterReload).toBeVisible({ timeout: 30_000 });
  const countAfterReload = await assistantLocator.count();
  const msg2 = `Follow-up ${Date.now()}: Thanks for restoring our conversation!`;
  await composerAfterReload.fill(msg2);
  await composerAfterReload.press('Enter');
  await expect.poll(() => assistantLocator.count(), { timeout: 90_000 }).toBeGreaterThan(countAfterReload);
  await page.waitForTimeout(2000);

  // Capture sanitized responsive screenshots at 1440, 1024, 768, 390
  for (const [w, h] of [[1440, 900], [1024, 768], [768, 1024], [390, 844]] as const) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${ARTIFACT_DIR}/klocal_chat_${w}px.png`, fullPage: false });
  }
});
