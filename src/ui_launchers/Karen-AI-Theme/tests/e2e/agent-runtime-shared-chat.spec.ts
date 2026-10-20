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
    await page.getByRole('button', { name: 'Agent Runtime', exact: true }).click();
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
    await page.getByRole('button', { name: 'Agent Runtime', exact: true }).click();
    await page.getByRole('button', { name: 'Ask Karen', exact: true }).last().click();
    await expect(page.getByTestId('persistent-karen-conversation')).toHaveCount(1);
  });
});
