import { expect, test } from '../../e2e/fixtures/verified-search-deployment';
import { openChat } from './helpers/chatRuntimeAudit';

/**
 * Explicit, real-account, real-provider acceptance. No route interception,
 * fake SSE, seeded credentials, transient model-name assertions or UI-only
 * success criteria. A saved answer must have a backend-issued generative
 * execution receipt bound to that exact assistant message.
 */
const enabled = process.env.KAREN_CHAT_GENERATION_LIVE_ACCEPTANCE === 'true';

test.describe('Canonical CopilotKit live generation', () => {
  test.skip(!enabled, 'Requires approved-host real-model acceptance');
  test.use({ trace: 'off', video: 'off', screenshot: 'off' });

  test('one real run persists provider-proven answer and survives reload', async ({ page }) => {
    test.setTimeout(180_000);
    await openChat(page);
    const shell = page.getByTestId('karen-copilot-consumer-chat');
    const askKaren = page.getByRole('button', { name: 'Ask Karen', exact: true });
    if (!(await shell.isVisible().catch(() => false)) &&
        await askKaren.isVisible().catch(() => false)) {
      await askKaren.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(shell.getByTestId('karen-copilot-controlled-chat')).toBeVisible();

    const previousId = await shell.getAttribute('data-conversation-id');
    await shell.getByRole('button', { name: 'New conversation' }).click();
    await expect.poll(async () => {
      const current = await shell.getAttribute('data-conversation-id');
      return current && current !== previousId ? current : null;
    }, { timeout: 30_000 }).not.toBeNull();

    const conversationId = await shell.getAttribute('data-conversation-id');
    expect(conversationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);

    const prompt = `Live chat generation acceptance ${crypto.randomUUID()}: Respond with one brief sentence.`;
    const runRequests: string[] = [];
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && [
        '/api/copilotkit/agent/default/run',
        '/api/chat/ag-ui',
        '/api/chat/stream',
      ].includes(path)) runRequests.push(path);
    });
    const composer = shell.getByTestId('karen-copilot-sdk-chat').locator('textarea').first();
    await expect(composer).toBeVisible();
    await composer.fill(prompt);
    await composer.press('Enter');

    let verifiedAssistantId = '';
    await expect.poll(async () => {
      const observation = await page.evaluate(async ({ id, sent }) => {
        const token = window.localStorage.getItem('access_token');
        const response = await fetch(
          `/api/copilotkit/threads/${encodeURIComponent(id)}/messages`,
          {
            credentials: 'same-origin',
            redirect: 'error',
            cache: 'no-store',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          },
        );
        if (!response.ok) return null;
        const body = await response.json() as {
          threadId?: string;
          messages?: Array<{ id?: string; role?: string; content?: string }>;
          replayEvents?: Array<{ type?: string; name?: string; messageId?: string; value?: Record<string, unknown> }>;
        };
        if (body.threadId !== id || !Array.isArray(body.messages) ||
            !Array.isArray(body.replayEvents)) return null;
        const users = body.messages.filter(message => message.role === 'user' && message.content === sent);
        if (users.length !== 1) return null;
        const index = body.messages.findIndex(message => message === users[0]);
        const answer = body.messages[index + 1];
        if (answer?.role !== 'assistant' || !answer.id || !answer.content?.trim()) return null;
        const receipts = body.replayEvents.filter(event =>
          event.type === 'CUSTOM' && event.name === 'karen.execution_receipt.v1' &&
          event.messageId === answer.id,
        );
        if (receipts.length !== 1) return null;
        const receipt = receipts[0].value;
        if (!receipt || typeof receipt !== 'object') return null;
        const actualProvider = receipt.actual_provider;
        const actualModel = receipt.actual_model;
        const responseSource = receipt.response_source;
        if ([actualProvider, actualModel, responseSource].some(value =>
          typeof value !== 'string' || !value.trim() ||
          ['none', 'unknown', 'unavailable'].includes(value.trim().toLowerCase()))) return null;
        if (!/(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/i.test(String(responseSource))) return null;
        return answer.id;
      }, { id: conversationId!, sent: prompt });
      if (observation) verifiedAssistantId = observation;
      return Boolean(observation);
    }, { timeout: 120_000, intervals: [1000, 2000, 3000],
      message: 'Real model execution must produce one persisted assistant turn and one bound receipt' })
      .toBe(true);

    expect(runRequests, 'A single submitted turn must produce exactly one run request').toHaveLength(1);
    await expect(shell.getByTestId('karen-copilot-assistant-message').last()).toBeVisible();
    expect(verifiedAssistantId).toMatch(/^[a-zA-Z0-9_-]{1,128}$/);

    await page.reload();
    const restored = page.getByTestId('karen-copilot-consumer-chat');
    await expect(restored).toBeVisible({ timeout: 30_000 });
    await expect(restored).toHaveAttribute('data-conversation-id', conversationId!);
    await expect(restored.getByTestId('karen-copilot-assistant-message').last())
      .toBeVisible({ timeout: 30_000 });
  });
});
