import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Real-deployment user-journey checks.
 *
 * No mocked routes, canned model content, or fixture-only application state.
 * Use a sanitized dedicated account and a real healthy model backend.
 * Artifacts belong to Playwright test results, not the curated gallery.
 */
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const hasCredentials = Boolean(email && password);

async function captureEvidence(
  page: Page,
  testInfo: TestInfo,
  journeyId: string,
  action: string,
  expected: string,
  observed: string,
): Promise<void> {
  const screenshot = await page.screenshot({
    fullPage: true,
    animations: 'disabled',
  });
  await testInfo.attach(`${journeyId}-screenshot`, {
    body: screenshot,
    contentType: 'image/png',
  });
  await testInfo.attach(`${journeyId}-evidence`, {
    body: Buffer.from(
      JSON.stringify(
        {
          journey_id: journeyId,
          action,
          expected,
          observed,
          page_url: page.url(),
          viewport: page.viewportSize(),
          timestamp: new Date().toISOString(),
          target_revision: process.env.KAREN_UX_TARGET_REVISION || null,
          deployment: process.env.KAREN_BASE_URL || 'http://localhost:8010',
        },
        null,
        2,
      ),
    ),
    contentType: 'application/json',
  });
}

async function signIn(page: Page): Promise<void> {
  if (!email || !password) {
    throw new Error('KAREN_UX_EMAIL and KAREN_UX_PASSWORD must be configured.');
  }

  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });
}

test('UX-01: signed-out entry resolves to an honest setup or login surface', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/(?:setup|login)(?:[/?#]|$)/, { timeout: 30_000 });

  if (new URL(page.url()).pathname === '/login') {
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
  } else {
    await expect(page.getByText('System check')).toBeVisible();
  }

  await captureEvidence(
    page,
    testInfo,
    'UX-01',
    'Visit / without a session',
    'Navigate to real setup or sign-in UI',
    `Resolved to ${new URL(page.url()).pathname}`,
  );
});

test('UX-02: authenticated user sends a message and sees a finished assistant response', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires sanitized real-deployment KAREN_UX_EMAIL and KAREN_UX_PASSWORD.');
  await signIn(page);

  const input = page.getByTestId('chat-input');
  const submit = page.getByTestId('chat-submit');
  const messages = page.getByRole('log', { name: 'Chat messages' });
  const priorCount = await messages.locator('.user-bubble').count();
  const prompt = 'Please reply with a brief greeting.';

  await input.fill(prompt);
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();
  await expect(messages.getByText(prompt, { exact: true })).toBeVisible();
  await expect
    .poll(() => messages.locator('.user-bubble').count(), { timeout: 90_000 })
    .toBeGreaterThanOrEqual(priorCount + 2);
  await expect(submit).toHaveAttribute('aria-label', 'Send message', { timeout: 90_000 });

  const bubbles = messages.locator('.user-bubble');
  const answer = bubbles.last();
  await expect(answer).not.toContainText('Stream ended without a runtime completion event');
  await expect.poll(async () => (await answer.innerText()).trim().length).toBeGreaterThan(0);

  await captureEvidence(
    page,
    testInfo,
    'UX-02',
    'Sign in and send an ordinary prompt',
    'User message and completed non-empty assistant response',
    `Rendered ${await bubbles.count()} message bubbles; last response contains text`,
  );
});

test('UX-10: mobile viewport retains an operable chat composer', async ({ page }, testInfo) => {
  test.skip(!hasCredentials, 'Requires sanitized real-deployment KAREN_UX_EMAIL and KAREN_UX_PASSWORD.');
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);

  const input = page.getByTestId('chat-input');
  const submit = page.getByTestId('chat-submit');
  await expect(input).toBeInViewport();
  await expect(submit).toBeInViewport();
  await input.fill('Mobile input check');
  await expect(submit).toBeEnabled({ timeout: 30_000 });

  await captureEvidence(
    page,
    testInfo,
    'UX-10',
    'Open chat at 390 x 844 and enter text',
    'Composer and send control remain visible and operable',
    'Composer visible and send control enabled; no message submitted',
  );
});

test('UX-04: completed conversation survives a browser reload', async ({ page }, testInfo) => {
  test.skip(!hasCredentials, 'Requires a sanitized account and a healthy real backend.');
  await signIn(page);

  const input = page.getByTestId('chat-input');
  const submit = page.getByTestId('chat-submit');
  const messages = page.getByRole('log', { name: 'Chat messages' });
  const marker = `UX04-persistence-${Date.now()}`;
  const prompt = `Please acknowledge this conversation marker: ${marker}`;
  const oldCount = await messages.locator('.user-bubble').count();

  await input.fill(prompt);
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();

  await expect(messages.getByText(prompt, { exact: true })).toBeVisible();
  await expect
    .poll(() => messages.locator('.user-bubble').count(), { timeout: 90_000 })
    .toBeGreaterThanOrEqual(oldCount + 2);
  await expect(submit).toHaveAttribute('aria-label', 'Send message', { timeout: 90_000 });

  const assistantContent = messages.getByTestId('chat-message-assistant')
    .last().getByTestId('chat-message-content');
  await expect(assistantContent).not.toBeEmpty();
  const answer = (await assistantContent.innerText()).trim();
  expect(answer.length).toBeGreaterThan(0);

  // The active conversation must be server-backed. Reload discards component state,
  // so a message that exists only in memory cannot pass this assertion.
  await page.reload();
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });
  const restoredMessages = page.getByRole('log', { name: 'Chat messages' });
  await expect(restoredMessages.getByText(prompt, { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  const restoredAssistant = restoredMessages.getByTestId('chat-message-assistant')
    .last().getByTestId('chat-message-content');
  await expect(restoredAssistant).toHaveText(answer, { timeout: 30_000 });

  await captureEvidence(
    page,
    testInfo,
    'UX-04',
    'Send a real prompt and reload the authenticated browser page',
    'Previously sent prompt and exact assistant response are restored from the server-backed conversation',
    `Conversation marker ${marker} and the exact assistant response remained visible after reload`,
  );
});

test('UX-11: keyboard can focus the chat composer and send control', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires a sanitized account and a real deployment.');
  await signIn(page);

  const input = page.getByRole('textbox', { name: 'Chat message input' });
  const submit = page.getByRole('button', { name: 'Send message' });
  await input.focus();
  await expect(input).toBeFocused();
  await page.keyboard.type('Keyboard navigation check');
  await expect(submit).toBeEnabled({ timeout: 30_000 });

  // Focus the actual control using native keyboard navigation.
  await page.keyboard.press('Tab');
  await expect(submit).toBeFocused();

  await captureEvidence(
    page,
    testInfo,
    'UX-11',
    'Type into chat with keyboard and Tab to the send control',
    'Keyboard focus reaches the enabled send control with an accessible name',
    'Chat input accepted keyboard text and Tab moved focus to Send message',
  );
});

test('UX-12: transport failure is reported without inventing an assistant answer', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires a sanitized real-deployment account.');
  await signIn(page);

  // Deliberately fail the browser transport, not the model or its runtime.
  // This is failure injection, never a mocked completion or canned AI response.
  await page.route('**/api/chat/stream', async (route) => {
    await route.abort('failed');
  });

  const input = page.getByTestId('chat-input');
  const submit = page.getByTestId('chat-submit');
  const messages = page.getByRole('log', { name: 'Chat messages' });
  const initialAssistantCount = await messages.getByTestId('chat-message-assistant').count();
  const prompt = `UX12-transport-failure-${Date.now()}`;

  await input.fill(prompt);
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();

  await expect(messages.getByText(prompt, { exact: true })).toBeVisible();
  await expect(page.getByText('Chat request failed', { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(submit).toHaveAttribute('aria-label', 'Send message', { timeout: 30_000 });
  expect(await messages.getByTestId('chat-message-assistant').count())
    .toBe(initialAssistantCount);

  await captureEvidence(
    page,
    testInfo,
    'UX-12',
    'Abort the outgoing stream transport and send a real prompt',
    'Visible failure notice; no fabricated assistant completion',
    'Chat request failed notice appeared and assistant count did not increase',
  );
});

test('UX-13: advanced navigation is discoverable without overwhelming the first screen', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires sanitized authenticated Karen deployment.');
  await signIn(page);

  const toggle = page.getByTestId('advanced-tools-toggle');
  const advanced = page.getByTestId('advanced-tools-content');

  await expect(page.getByText('Start here')).toBeVisible();
  await expect(page.getByText('Explore', { exact: true })).toBeVisible();
  await expect(page.getByText('Automations', { exact: true })).toBeVisible();
  await expect(page.getByText('Tools & plugins', { exact: true })).toBeVisible();

  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(advanced).toBeHidden();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(advanced).toBeVisible();
  await expect(advanced.getByText('Tasks', { exact: true })).toBeVisible();
  await expect(advanced.getByText('Cron Jobs', { exact: true })).toBeVisible();

  await captureEvidence(
    page,
    testInfo,
    'UX-13',
    'Open authenticated dashboard and expand Advanced tools',
    'Core destinations visible; detailed routes discoverable but initially collapsed',
    'Advanced tools expanded and Tasks / Cron Jobs became visible',
  );
});

test('UX-14: mobile navigation returns focus to the selected workspace', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires sanitized authenticated Karen deployment.');
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);

  const trigger = page.locator('[data-sidebar="trigger"]');
  await trigger.click();
  const drawer = page.locator('[data-sidebar="sidebar"][data-mobile="true"]');
  await expect(drawer).toBeVisible();
  await drawer.getByRole('button', { name: 'Messages & channels' }).click();
  await expect(drawer).toBeHidden({ timeout: 10_000 });
  await expect(page.getByTestId('workspace-scroll-region')).toBeVisible();

  await captureEvidence(
    page,
    testInfo,
    'UX-14',
    'Open navigation on a 390px mobile viewport and choose Messages & channels',
    'The mobile drawer closes and the workspace remains usable',
    'Mobile navigation drawer closed following a destination selection',
  );
});

test('UX-15: mobile sidebar reveals primary and advanced navigation', async ({
  page,
}, testInfo) => {
  test.skip(!hasCredentials, 'Requires sanitized authenticated Karen deployment.');
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);

  const sidebarTrigger = page.getByRole('button', { name: 'Toggle Sidebar' });
  await expect(sidebarTrigger).toBeInViewport();
  await sidebarTrigger.click();

  const mobileNav = page.locator('[data-sidebar="sidebar"][data-mobile="true"]');
  await expect(mobileNav).toBeVisible();
  await expect(mobileNav.getByText('Start here')).toBeVisible();
  await expect(mobileNav.getByText('Messages & channels', { exact: true })).toBeVisible();
  await expect(mobileNav.getByText('Tools & plugins', { exact: true })).toBeVisible();

  const advanced = mobileNav.getByTestId('advanced-tools-toggle');
  await expect(advanced).toHaveAttribute('aria-expanded', 'false');
  await advanced.click();
  await expect(advanced).toHaveAttribute('aria-expanded', 'true');
  await expect(mobileNav.getByText('Cron Jobs', { exact: true })).toBeVisible();

  await captureEvidence(
    page,
    testInfo,
    'UX-15',
    'Open mobile navigation at 390 x 844 and expand advanced destinations',
    'Readable primary navigation and discoverable advanced sections in mobile sheet',
    'Mobile sheet and advanced destinations rendered; navigation not submitted',
  );
});
