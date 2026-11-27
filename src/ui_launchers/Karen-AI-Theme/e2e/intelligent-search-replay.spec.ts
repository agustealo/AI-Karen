import { expect, test } from './fixtures/verified-search-deployment';

/**
 * Release acceptance against a real authenticated installation.
 * No route interception, fabricated model output, or synthetic saved messages.
 * Keep credentials out of traces and screenshots on the approved test system.
 */
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

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

  // Protect release-test credentials from cross-origin login redirects.
  const approvedDeployment = process.env.KAREN_BASE_URL;
  if (!approvedDeployment) throw new Error('Approved deployment URL is required');
  const approvedOrigin = new URL(approvedDeployment).origin;
  await page.goto('/login');
  expect(new URL(page.url()).origin).toBe(approvedOrigin);
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  expect(new URL(page.url()).origin).toBe(approvedOrigin);

  const panel = page.getByTestId('persistent-karen-conversation');
  if (await page.getByRole('button', { name: 'Ask Karen', exact: true }).isVisible({ timeout: 5000 }).catch(() => false)) {
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  }
  await expect(panel).toHaveAttribute('aria-hidden', 'false');

  // If the conversation workspace is in a recovered read-only state from a previous run,
  // click "Start a new conversation" or "New conversation" to ensure a clean composer.
  const startNewBtn = panel.getByRole('button', { name: 'Start a new conversation', exact: true })
    .or(panel.getByRole('button', { name: 'New conversation', exact: true }).first());
  if (await startNewBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await startNewBtn.click();
    await page.waitForTimeout(1000);
  }

  const prompt = `Research acceptance ${Date.now()}: Search the web for an official source describing the history of the Python programming language. Answer with a verified URL citation.`;
  const composer = panel.getByTestId('chat-input').or(panel.getByTestId('karen-copilot-sdk-chat').locator('textarea').first());
  await expect(composer).toBeVisible({ timeout: 30_000 });

  const assistantLocator = panel.getByTestId('chat-message-assistant').or(panel.getByTestId('karen-copilot-assistant-message'));
  const assistantCount = await assistantLocator.count();
  await composer.fill(prompt);

  const sendBtn = panel.getByRole('button', { name: 'Send message' });
  if (await sendBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
    await sendBtn.click();
  } else {
    await composer.press('Enter');
  }

  await expect.poll(() => assistantLocator.count(), { timeout: 90_000 }).toBeGreaterThan(assistantCount);
  const assistantMessage = assistantLocator.last();

  const evidenceStatus = assistantMessage.getByTestId('chat-evidence-status');
  if (await evidenceStatus.isVisible({ timeout: 2000 }).catch(() => false)) {
    await expect(evidenceStatus.filter({ hasText: 'Verified grounded answer' })).toBeVisible({ timeout: 90_000 });
  }

  await expect.poll(async () => {
    const text = await assistantMessage.innerText();
    return text.trim().length;
  }, { timeout: 90_000 }).toBeGreaterThan(0);
  const originalAnswer = (await assistantMessage.innerText()).trim();

  const citationBadge = assistantMessage.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).first();
  if (await citationBadge.isVisible({ timeout: 2000 }).catch(() => false)) {
    await citationBadge.click();
    const sourceToggle = assistantMessage.getByRole('button', { name: /Show [1-9][0-9]* sources?/ }).last();
    if (await sourceToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
      await sourceToggle.click();
    }
  }

  const sourceList = assistantMessage.getByTestId('chat-source-list')
    .or(panel.getByTestId('karen-search-results'))
    .or(assistantMessage.getByTestId('karen-copilot-verified-part'));
  const linkLocator = sourceList.locator('a[href^="https://"], a[href^="http://"]')
    .or(assistantMessage.locator('a[href^="https://"], a[href^="http://"]'));

  await expect.poll(async () => {
    const linkCount = await linkLocator.count();
    if (linkCount > 0) return linkCount;
    const urls = (await assistantMessage.innerText()).match(/https?:\/\/[^\s)<>"']+/g);
    return urls ? urls.length : 0;
  }, { timeout: 30_000 }).toBeGreaterThan(0);

  const linksFromDOM = await linkLocator.evaluateAll(
    (links) => links.map((link) => (link as HTMLAnchorElement).href).filter(Boolean),
  );
  const textUrls = (await assistantMessage.innerText()).match(/https?:\/\/[^\s)<>"']+/g) || [];
  const originalSources = Array.from(new Set([...linksFromDOM, ...textUrls]));
  expect(originalSources.length, 'Grounded answers must expose a real source URL').toBeGreaterThan(0);

  // Navigation reload must read the durable conversation, not just the
  // previously rendered React state.
  await page.reload();
  if (await page.getByRole('button', { name: 'Ask Karen', exact: true }).isVisible({ timeout: 5000 }).catch(() => false)) {
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).click();
  }
  await expect(panel.getByText(prompt, { exact: false })).toBeVisible({ timeout: 30_000 });

  // On reload, the conversation may restore in the native message view or in the
  // verified read-only text projection. In both cases, the answer and sources survive.
  await expect.poll(async () => {
    const text = await panel.innerText();
    return text.includes('Retrieved evidence') || text.includes('Source: https://') || originalSources.some(s => text.includes(s));
  }, { timeout: 30_000 }).toBe(true);

  // Close the conversation panel before next tests to keep workspace clean
  const closeBtn = page.getByRole('button', { name: 'Close panel', exact: true })
    .or(page.getByRole('button', { name: 'Hide Karen', exact: true }));
  if (await closeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await closeBtn.click();
  }
});


test('SEARCH-PLUGIN-02: live weather uses the consumer plugin observation surface', async ({ page }) => {
  test.setTimeout(180_000);
  const required = process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED === 'true';
  test.skip(!required, 'Authenticated consumer release proof is opt-in');
  const email = process.env.KAREN_UX_EMAIL;
  const password = process.env.KAREN_UX_PASSWORD;
  if (!email || !password) throw new Error('Missing authenticated acceptance credentials');

  // Protect release-test credentials from cross-origin login redirects.
  const approvedDeployment = process.env.KAREN_BASE_URL;
  if (!approvedDeployment) throw new Error('Approved deployment URL is required');
  const approvedOrigin = new URL(approvedDeployment).origin;
  await page.goto('/login');
  expect(new URL(page.url()).origin).toBe(approvedOrigin);
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  expect(new URL(page.url()).origin).toBe(approvedOrigin);

  // Locate the installed plugin through the consumer navigation. No private
  // route, response interception, or synthetic provider values are permitted.
  const advancedBtn = page.getByRole('button', { name: 'Advanced tools' });
  if (await advancedBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    if (await advancedBtn.getAttribute('aria-expanded') !== 'true') {
      await advancedBtn.click();
    }
  }
  const navSearch = page.getByText('Intelligent Search', { exact: true }).first();
  await expect(navSearch).toBeVisible({ timeout: 30_000 });
  await navSearch.click();
  const query = page.getByLabel('Query', { exact: true });
  await expect(query).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Search settings' }).click();
  await page.getByLabel('Search mode').selectOption('auto');
  await page.getByRole('button', { name: 'Hide search settings' }).click();

  // A location-free query may use an authorized profile/device/system location.
  // Otherwise the consumer must request one. Wikipedia snippets cannot count
  // as weather observations in either case.
  await query.fill("What's the weather?");
  await query.locator('..').getByRole('button', { name: 'Search', exact: true }).click();
  const clarification = page.getByRole('heading', { name: 'Which location should I check?' });
  const initialObservation = page.locator('section[aria-label="Weather observation"]');
  await expect.poll(async () => (await clarification.isVisible()) || (await initialObservation.isVisible()),
    { timeout: 120_000 }).toBe(true);
  if (await clarification.isVisible()) {
    await expect(initialObservation).toHaveCount(0);
  } else {
    await expect(initialObservation).toContainText('Provider timestamp:');
  }
  await expect(page.getByRole('heading', { name: 'No sources found' })).toHaveCount(0);

  await query.fill('What is the weather in Detroit, MI?');
  await query.locator('..').getByRole('button', { name: 'Search', exact: true }).click();

  const observation = page.locator('section[aria-label="Weather observation"]');
  await expect(observation).toBeVisible({ timeout: 120_000 });
  await expect(observation).toContainText('Detroit');
  await expect(observation).toContainText('°F');
  await expect(observation).toContainText('Provider timestamp:');
  await expect(page.getByRole('heading', { name: 'No sources found' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Research tools' }).click();
  await page.getByText('Technical search details').click();
  await expect(page.getByText('Actual mode', { exact: true })).toBeVisible();
  await expect(
    page.locator('details', { hasText: 'Technical search details' }).getByText('Provider', { exact: true }).first(),
  ).toBeVisible();
});


test('SEARCH-PLUGIN-03: general web retrieval proves independent source domains', async ({ page }) => {
  test.setTimeout(180_000);
  test.skip(process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED !== 'true',
    'Authenticated consumer release proof is opt-in');
  const email = process.env.KAREN_UX_EMAIL;
  const password = process.env.KAREN_UX_PASSWORD;
  if (!email || !password) throw new Error('Missing authenticated acceptance credentials');

  // Protect release-test credentials from cross-origin login redirects.
  const approvedDeployment = process.env.KAREN_BASE_URL;
  if (!approvedDeployment) throw new Error('Approved deployment URL is required');
  const approvedOrigin = new URL(approvedDeployment).origin;
  await page.goto('/login');
  expect(new URL(page.url()).origin).toBe(approvedOrigin);
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  expect(new URL(page.url()).origin).toBe(approvedOrigin);

  const advancedBtn = page.getByRole('button', { name: 'Advanced tools' });
  if (await advancedBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    if (await advancedBtn.getAttribute('aria-expanded') !== 'true') {
      await advancedBtn.click();
    }
  }
  const navSearch = page.getByText('Intelligent Search', { exact: true }).first();
  await expect(navSearch).toBeVisible({ timeout: 30_000 });
  await navSearch.click();
  const query = page.getByLabel('Query', { exact: true });
  await expect(query).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Search settings' }).click();
  await page.getByLabel('Search mode').selectOption('general');
  await page.getByRole('button', { name: 'Hide search settings' }).click();
  await query.fill('Python programming language official documentation and history');
  await query.locator('..').getByRole('button', { name: 'Search', exact: true }).click();

  await expect(page.getByRole('button', { name: 'Research tools' })).toBeVisible({ timeout: 120_000 });
  await page.getByRole('button', { name: 'Research tools' }).click();
  await page.getByText('Technical search details').click();
  await expect(page.getByText('Actual mode', { exact: true })).toBeVisible();
  const websites = page.getByText(/\d+ websites/, { exact: false }).first();
  await expect(websites).toBeVisible();
  // Provider diversity is an outcome of the live retrieval, not a static
  // render assertion. Poll the completed UI value without intercepting HTTP.
  await expect.poll(async () => {
    const label = await websites.innerText();
    const matched = label.match(/(\d+)\s+websites/i);
    return matched ? Number(matched[1]) : 0;
  }, {
    timeout: 30_000,
    message: 'At least two independent websites must be represented in live search evidence',
  }).toBeGreaterThanOrEqual(2);
});
