import { expect, Page, APIRequestContext, test } from '@playwright/test';

export type RuntimeProviderModel = {
  id: string;
  label?: string;
  name?: string;
  available?: boolean;
  default?: boolean;
};

export type RuntimeProvider = {
  id: string;
  label?: string;
  display_name?: string;
  enabled?: boolean;
  configured?: boolean;
  healthy?: boolean;
  allowed_for_current_user?: boolean;
  requires_api_key?: boolean;
  runtime_engine?: string;
  category?: string;
  models?: RuntimeProviderModel[];
};

export type RuntimeProviderCatalog = {
  providers: RuntimeProvider[];
  default_provider?: string;
  default_model?: string;
  fallback_order?: string[];
};

export async function fetchRuntimeCatalog(page: Page): Promise<RuntimeProviderCatalog> {
  const catalog = await page.evaluate(async () => {
    const response = await fetch('/api/runtime/providers');
    if (!response.ok) throw new Error(`GET /api/runtime/providers failed: ${response.status}`);
    return response.json();
  });
  return catalog;
}

export function getAuditableProviders(catalog: RuntimeProviderCatalog): RuntimeProvider[] {
  return (catalog.providers || []).filter((provider) => {
    const models = provider.models || [];
    return (
      provider.enabled !== false &&
      provider.configured !== false &&
      provider.allowed_for_current_user !== false &&
      models.length > 0
    );
  });
}

export function pickProviderModel(provider: RuntimeProvider): RuntimeProviderModel {
  const models = provider.models || [];
  const defaultModel = models.find((model) => model.default);
  return defaultModel || models[0];
}

export async function openChat(page: Page): Promise<void> {
  await page.goto('/');
  
  // If redirected to login, perform authentication
  if (page.url().includes('/login')) {
    // Switch to Email mode (the first button in the toggle)
    const emailButton = page.locator('button:has-text("Email")');
    if (await emailButton.isVisible()) {
      await emailButton.click();
    }
    
    await page.fill('input[name="email"]', 'admin@karen.ai');
    await page.fill('input[name="password"]', 'Admin@123!');
    await page.click('button[type="submit"]');
    
    // Wait for redirect to dashboard/chat
    await expect(page).toHaveURL(/.*dashboard|.*chat|.*\//, { timeout: 30000 });
  }

  await expect(page.getByTestId('chat-root')).toBeVisible({ timeout: 60_000 });
}

export async function selectProviderAndModel(
  page: Page,
  providerId: string,
  modelId: string,
): Promise<void> {
  const providerSelect = page.getByTestId('chat-provider-select');
  
  // Wait for the options to be populated in the select
  try {
    await expect(providerSelect.locator('option')).not.toHaveCount(0, { timeout: 10000 });
  } catch (e) {
    const html = await providerSelect.innerHTML();
    console.error(`Provider select options empty. HTML: ${html}`);
    throw e;
  }
  
  // Select provider
  const providerOption = providerSelect.locator(`option[value="${providerId}"]`);
  if (!(await providerOption.count())) {
    const options = await providerSelect.locator('option').allInnerTexts();
    throw new Error(`Provider "${providerId}" not found in select. Available: ${options.join(', ')}`);
  }

  await providerSelect.selectOption(providerId);
  await expect(providerSelect.first()).toHaveValue(providerId, { timeout: 10000 });

  const modelSelect = page.getByTestId('chat-model-select');
  // Model options change based on provider, so wait for them to update
  try {
    await expect(modelSelect.locator(`option[value="${modelId}"]`).first()).toBeAttached({ timeout: 10000 });
  } catch (e) {
    const options = await modelSelect.locator('option').allInnerTexts();
    throw new Error(`Model "${modelId}" not found for provider "${providerId}" in select. Available: ${options.join(', ')}`);
  }
  
  await modelSelect.selectOption(modelId);
  await expect(modelSelect.first()).toHaveValue(modelId, { timeout: 10000 });
}

export async function sendAuditPrompt(page: Page): Promise<void> {
  await page.getByTestId('chat-input').fill(
    'Reply with exactly this phrase and nothing else: KAREN_RUNTIME_AUDIT_OK',
  );
  await page.getByTestId('chat-submit').click();
}

export async function waitForAssistantResponse(page: Page): Promise<void> {
  await expect(page.getByTestId('chat-message-assistant').last()).toBeVisible({
    timeout: 120_000,
  });

  const text = await page.getByTestId('chat-message-assistant').last().innerText();
  expect(text.trim().length, 'Assistant response was empty').toBeGreaterThan(0);
}

export async function openResponseDetails(page: Page): Promise<void> {
  const lastAssistantMessage = page.locator('.message-assistant').last();
  const toggle = lastAssistantMessage.getByTestId('chat-response-details-toggle');
  
  if (!(await toggle.isVisible())) {
    const content = await lastAssistantMessage.innerText();
    console.error(`Metadata toggle not visible for message: "${content.slice(0, 100)}..."`);
    // Check if there is any hidden metadata info
    throw new Error('Forensic metadata toggle not found on the assistant message.');
  }

  await toggle.click();

  try {
    await expect(page.getByTestId('chat-response-details-panel').last()).toBeVisible({
      timeout: 10_000,
    });
  } catch (e) {
    console.error('Forensic details panel failed to appear after toggle click.');
    throw e;
  }
}

export async function expectForensicMetadata(page: Page): Promise<void> {
  await expect(page.getByTestId('chat-requested-provider').last()).toBeVisible();
  await expect(page.getByTestId('chat-requested-model').last()).toBeVisible();
  await expect(page.getByTestId('chat-actual-provider').last()).toBeVisible();
  await expect(page.getByTestId('chat-actual-model').last()).toBeVisible();
  await expect(page.getByTestId('chat-runtime-engine').last()).toBeVisible();
  await expect(page.getByTestId('chat-response-source').last()).toBeVisible();
  await expect(page.getByTestId('chat-fallback-level').last()).toBeVisible();
  await expect(page.getByTestId('chat-correlation-id').last()).toBeVisible();

  const actualProvider = await page.getByTestId('chat-actual-provider').last().innerText();
  const runtimeEngine = await page.getByTestId('chat-runtime-engine').last().innerText();
  const correlationId = await page.getByTestId('chat-correlation-id').last().innerText();

  expect(actualProvider.trim(), 'Actual provider missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
  expect(runtimeEngine.trim(), 'Runtime engine missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
  expect(correlationId.trim(), 'Correlation ID missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
}

export async function expectRequestedProviderReflected(
  page: Page,
  providerId: string,
  modelId: string,
): Promise<void> {
  const requestedProvider = await page.getByTestId('chat-requested-provider').last().innerText();
  const requestedModel = await page.getByTestId('chat-requested-model').last().innerText();

  expect(requestedProvider.toLowerCase()).toContain(providerId.toLowerCase().replace('builtin_', '').split('_')[0]);
  expect(requestedModel.length).toBeGreaterThan(0);

  if (modelId !== 'auto') {
    expect(requestedModel.toLowerCase()).toContain(modelId.toLowerCase().split('/').pop()!.slice(0, 8));
  }
}

export async function expectNoFakeSuccess(page: Page): Promise<void> {
  const assistantText = await page.getByTestId('chat-message-assistant').last().innerText();

  const forbiddenFakeSuccess = [
    "I'm currently experiencing some technical difficulties",
    "can only provide limited responses",
    "try again later when the system is fully operational",
  ];

  for (const phrase of forbiddenFakeSuccess) {
    expect(
      assistantText,
      `Response looks like hardcoded degraded text: ${phrase}`,
    ).not.toContain(phrase);
  }
}
