import { test, expect } from '@playwright/test';
import {
  openChat,
  sendAuditPrompt,
  waitForAssistantResponse,
  openResponseDetails,
  expectForensicMetadata,
} from './helpers/chatRuntimeAudit';

test.describe('Chat runtime forensic mocked fallback states', () => {
  test('renders vLLM fallback truth when requested provider fails', async ({ page }) => {
    const metadata = {
      degraded_mode: true,
      requested_provider: 'gemini',
      requested_model: 'gemini-2.5-flash',
      actual_provider: 'builtin_vllm',
      actual_model: 'auto',
      runtime_engine: 'vllm',
      fallback_level: 1,
      response_source: 'builtin_provider_engine',
      correlation_id: 'corr-playwright-vllm-fallback',
      llm: {
        requested_provider: 'gemini',
        requested_model: 'gemini-2.5-flash',
        actual_provider: 'builtin_vllm',
        actual_model: 'auto',
        runtime_engine: 'vllm',
        fallback_level: 1,
        response_source: 'builtin_provider_engine',
        used_fallback: true,
        is_degraded: true,
        correlation_id: 'corr-playwright-vllm-fallback',
      }
    };

    await page.route('**/api/copilot/assist/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          `data: ${JSON.stringify({ type: 'content', content: 'KAREN_RUNTIME_AUDIT_OK' })}\n\n`,
          `data: ${JSON.stringify({ type: 'complete', content: 'KAREN_RUNTIME_AUDIT_OK', metadata })}\n\n`,
          'data: [DONE]\n\n'
        ].join(''),
      });
    });

    await openChat(page);
    await sendAuditPrompt(page);
    await waitForAssistantResponse(page);
    await openResponseDetails(page);
    await expectForensicMetadata(page);

    await expect(page.getByTestId('chat-requested-provider').last()).toContainText(/gemini/i);
    await expect(page.getByTestId('chat-actual-provider').last()).toContainText(/vllm/i);
    await expect(page.getByTestId('chat-runtime-engine').last()).toContainText(/vllm/i);
    await expect(page.getByTestId('chat-fallback-level').last()).toContainText(/1/);
  });

  test('renders emergency unavailable honestly without fake model success', async ({ page }) => {
    const metadata = {
      degraded_mode: true,
      requested_provider: 'gemini',
      requested_model: 'gemini-2.5-flash',
      actual_provider: 'none',
      actual_model: 'none',
      runtime_engine: 'none',
      fallback_level: 99,
      response_source: 'emergency_unavailable',
      correlation_id: 'corr-playwright-emergency',
      failure_reason: 'all_runtime_providers_unavailable',
      llm: {
        requested_provider: 'gemini',
        requested_model: 'gemini-2.5-flash',
        actual_provider: 'none',
        actual_model: 'none',
        runtime_engine: 'none',
        fallback_level: 99,
        response_source: 'emergency_unavailable',
        used_fallback: false,
        is_degraded: true,
        failure_reason: 'all_runtime_providers_unavailable',
        correlation_id: 'corr-playwright-emergency',
      }
    };

    await page.route('**/api/copilot/assist/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          `data: ${JSON.stringify({ type: 'content', content: 'Requested provider unavailable and no fallback model could answer.' })}\n\n`,
          `data: ${JSON.stringify({ type: 'complete', content: 'Requested provider unavailable and no fallback model could answer.', metadata })}\n\n`,
          'data: [DONE]\n\n'
        ].join(''),
      });
    });

    await openChat(page);
    await sendAuditPrompt(page);
    await waitForAssistantResponse(page);
    await openResponseDetails(page);

    await expect(page.getByTestId('chat-response-source').last()).toContainText(/emergency|unavailable/i);
    await expect(page.getByTestId('chat-fallback-level').last()).toContainText(/99/);
    await expect(page.getByTestId('chat-degraded-status').last()).toContainText(/degraded|emergency|unavailable/i);
  });
});
