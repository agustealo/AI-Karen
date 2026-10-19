import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Live, authenticated personal-context replay. Never intercept model replies,
 * invent memory writes, or treat screenshots as evidence of durable persistence.
 * Run only with a dedicated sanitized account and real healthy local runtime.
 */
const enabled = process.env.KAREN_UX_IDENTITY_REPLAY === 'true';
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;

async function signIn(page: Page): Promise<void> {
  if (!email || !password) throw new Error('Sanitized account credentials are required');
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });
}

async function sendAndRead(page: Page, prompt: string): Promise<string> {
  const messages = page.getByRole('log', { name: 'Chat messages' });
  const answers = messages.getByTestId('chat-message-assistant')
    .getByTestId('chat-message-content');
  const previous = await answers.count();
  const input = page.getByTestId('chat-input');
  const submit = page.getByTestId('chat-submit');
  await input.fill(prompt);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(messages.getByText(prompt, { exact: true })).toBeVisible();
  await expect.poll(() => answers.count(), { timeout: 120_000 })
    .toBeGreaterThan(previous);
  await expect(submit).toHaveAttribute('aria-label', 'Send message', { timeout: 120_000 });
  const text = (await answers.last().innerText()).trim();
  expect(text.length).toBeGreaterThan(0);
  expect(text).not.toMatch(/stream ended without a runtime completion event/i);
  return text;
}

test('UX-ID-01: current name and summary followup stay grounded in a real conversation', async ({
  page,
}, testInfo: TestInfo) => {
  test.skip(
    !enabled || !email || !password,
    'Opt-in only: sanitized account, healthy real backend, and KAREN_UX_IDENTITY_REPLAY=true',
  );
  // Five real model turns plus a server-backed reload can exceed the
  // generic 60-second UI-contract timeout on small local hardware.
  test.setTimeout(8 * 60_000);
  await signIn(page);
  const hello = await sendAndRead(page, 'Hello');
  expect(hello).not.toMatch(/not sure what specific need|clarify your intention/i);

  const acknowledgement = await sendAndRead(page, 'My name is Zeus');
  expect(acknowledgement).toMatch(/Zeus/i);

  const nameAnswer = await sendAndRead(page, "What's my name?");
  expect(nameAnswer).toMatch(/Zeus/i);
  expect(nameAnswer).not.toMatch(/don't have verified saved information/i);

  const summary = await sendAndRead(page, 'What can you share about me?');
  expect(summary).not.toMatch(/you are an AI created by|you are a language model/i);

  const followup = await sendAndRead(page, 'share please');
  expect(followup).not.toMatch(/you are an AI created by|you are a language model/i);
  expect(followup).toMatch(/Zeus/i);

  // Reload discards React component state. Both the user's last prompt and
  // the exact assistant answer must be restored by the canonical backend.
  await page.reload();
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });
  const restored = page.getByRole('log', { name: 'Chat messages' });
  await expect(restored.getByText('share please', { exact: true }).last())
    .toBeVisible({ timeout: 30_000 });
  const restoredAnswer = restored.getByTestId('chat-message-assistant')
    .last().getByTestId('chat-message-content');
  await expect(restoredAnswer).toHaveText(followup, { timeout: 30_000 });

  await testInfo.attach('UX-ID-01-live-conversation', {
    body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
    contentType: 'image/png',
  });
  await testInfo.attach('UX-ID-01-assertion-receipt', {
    body: Buffer.from(JSON.stringify({
      test: 'UX-ID-01',
      checked: ['greeting', 'name_acknowledgement', 'name_recall', 'summary', 'followup', 'reload_restoration'],
      target_revision: process.env.KAREN_UX_TARGET_REVISION || null,
      timestamp: new Date().toISOString(),
      // UI restoration is evidence of server-backed transcript retrieval,
      // not proof of NeuroVault long-term memory projection.
      runtime_persistence_verified: false,
      video_capture_opt_in: process.env.KAREN_E2E_CAPTURE_VIDEO === 'true',
    }, null, 2)),
    contentType: 'application/json',
  });
});
