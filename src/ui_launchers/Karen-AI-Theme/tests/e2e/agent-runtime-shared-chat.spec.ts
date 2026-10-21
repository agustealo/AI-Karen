import { test, expect } from '@playwright/test';
import { openChat } from './helpers/chatRuntimeAudit';

/**
 * Real-browser continuity smoke. Requires a running authenticated Karen
 * instance; does not mock runtime history, permissions, or model output.
 */
test.describe('Karen shared conversation workspace', () => {
  test('retains one mounted conversation when opening and closing the work panel', async ({ page }) => {
    await openChat(page);
    const conversation = page.getByTestId('persistent-karen-conversation');
    await expect(conversation).toBeVisible();

    // Navigate through the actual dashboard menu, not a test-only view setter.
    await page.getByRole('button', { name: 'Agents', exact: true }).first().click();
    await expect(page.getByTestId('workspace-scroll-region')).toBeVisible();
    await expect(conversation).toBeHidden();

    const launcher = page.getByRole('button', { name: 'Ask Karen', exact: true }).last();
    await launcher.click();
    await expect(conversation).toBeVisible();
    await expect(conversation).toHaveAttribute('role', 'dialog');
    await expect(conversation).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(conversation).toBeHidden();
    await expect(launcher).toBeFocused();
  });

  test('chat has only one persistent conversation container after workspace navigation', async ({ page }) => {
    await openChat(page);
    await expect(page.getByTestId('persistent-karen-conversation')).toHaveCount(1);
    await page.getByRole('button', { name: 'Agents', exact: true }).first().click();
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).last().click();
    await expect(page.getByTestId('persistent-karen-conversation')).toHaveCount(1);
  });
  test('keeps a single conversation and preserves its composer through panel navigation', async ({ page }) => {
    await openChat(page);
    const mounted = page.getByTestId('persistent-karen-conversation');
    const original = await mounted.locator('[data-testid="chat-input"]').count();
    const draft = 'Browser continuity draft, not submitted';
    if (original > 0) await mounted.getByTestId('chat-input').fill(draft);
    // The assistant-ui feature flag uses a different composer; this case
    // asserts lifecycle continuity without imposing legacy UI selectors.
    await page.getByRole('button', { name: 'Agents', exact: true }).first().click();
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).last().click();
    await expect(mounted).toBeVisible();
    await expect(mounted).toHaveCount(1);
    if (original > 0) {
      await expect(mounted.getByTestId('chat-input')).toBeVisible();
      await expect(mounted.getByTestId('chat-input')).toHaveValue(draft);
    }
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).last().click();
    await expect(mounted).toHaveCount(1);
    if (original > 0) await expect(mounted.getByTestId('chat-input')).toHaveValue(draft);
  });

  test('backend denies an unverified execution reference', async ({ page }) => {
    await openChat(page);
    await page.getByRole('button', { name: 'Agents', exact: true }).first().click();
    await expect(page.getByTestId('agent-workspace')).toBeVisible();
    // This only establishes unknown-resource denial; cross-user isolation
    // is covered by the backend ownership tests, not this browser smoke.
    const response = await page.request.get('/api/agent-runtime/my-runs/nonexistent-browser-journey');
    expect([401, 403, 404]).toContain(response.status());
  });

});
