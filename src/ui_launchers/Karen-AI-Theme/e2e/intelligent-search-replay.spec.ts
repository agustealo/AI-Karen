import { expect, test } from '@playwright/test';

/**
 * Release acceptance against a real authenticated installation.
 * No route interception, fabricated model output, or synthetic saved messages.
 * Keep credentials out of traces and screenshots on the approved test system.
 */
test('SEARCH-REPLAY-01: live grounded citations survive conversation reopening', async ({ page }) => {
  test.setTimeout(180_000); // Live retrieval and generation exceed the default 60s browser timeout.
  const required = process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED === 'true';
  const email = process.env.KAREN_UX_EMAIL;
  const password = process.env.KAREN_UX_PASSWORD;
  if (required && (!email || !password)) {
    throw new Error('Live search replay acceptance requires KAREN_UX_EMAIL and KAREN_UX_PASSWORD');
  }
  test.skip(!required, 'Opt-in live release acceptance on a sanitized authenticated deployment');
  if (!email || !password) throw new Error('Missing authenticated acceptance credentials');

  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });

  const panel = page.getByTestId('persistent-karen-conversation');
  await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  await expect(panel).toHaveAttribute('aria-hidden', 'false');
  const prompt = 'Search the web for an official source describing the history of the Python programming language. Answer with a verified URL citation.';
  await panel.getByTestId('chat-input').fill(prompt);
  await panel.getByRole('button', { name: 'Send message' }).click();

  const assistantMessage = panel.getByTestId('chat-message-assistant').last();
  const assistant = assistantMessage.getByTestId('chat-evidence-status').filter({ hasText: 'Verified grounded answer' });
  await expect(assistant).toBeVisible({ timeout: 90_000 });
  const citationBadge = assistantMessage.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).first();
  await expect(citationBadge).toBeVisible();
  await citationBadge.click();
  const sourceToggle = assistantMessage.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).last();
  await expect(sourceToggle).toBeVisible();
  await sourceToggle.click();
  await expect(assistantMessage.getByTestId('chat-source-list')).toBeVisible();
  const originalSources = await assistantMessage.getByTestId('chat-source-list').locator('a[href^="https://"], a[href^="http://"]').evaluateAll(
    (links) => links.map((link) => (link as HTMLAnchorElement).href).filter(Boolean),
  );
  expect(originalSources.length, 'Grounded answers must expose a real source URL').toBeGreaterThan(0);

  // Navigation reload must read the durable conversation, not just the
  // previously rendered React state.
  await page.reload();
  await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  await expect(panel.getByText(prompt, { exact: true })).toBeVisible({ timeout: 30_000 });
  const restoredMessage = panel.getByTestId('chat-message-assistant').last();
  await expect(restoredMessage.getByTestId('chat-evidence-status').filter({ hasText: 'Verified grounded answer' })).toBeVisible();
  const assistantMessageAfterReload = restoredMessage;
  const restoredBadge = assistantMessageAfterReload.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).first();
  await expect(restoredBadge).toBeVisible();
  await restoredBadge.click();
  await assistantMessageAfterReload.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).last().click();
  await expect(assistantMessageAfterReload.getByTestId('chat-source-list')).toBeVisible();
  const restoredSources = await assistantMessageAfterReload.getByTestId('chat-source-list').locator('a[href^="https://"], a[href^="http://"]').evaluateAll(
    (links) => links.map((link) => (link as HTMLAnchorElement).href).filter(Boolean),
  );
  expect(restoredSources).toEqual(originalSources);
});
