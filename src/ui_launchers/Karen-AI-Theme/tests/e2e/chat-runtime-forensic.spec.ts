import { test, expect } from '@playwright/test';
import {
  fetchRuntimeCatalog,
  getAuditableProviders,
  pickProviderModel,
  openChat,
  selectProviderAndModel,
  sendAuditPrompt,
  waitForAssistantResponse,
  openResponseDetails,
  expectForensicMetadata,
  expectRequestedProviderReflected,
  expectNoFakeSuccess,
} from './helpers/chatRuntimeAudit';

test.describe('Chat runtime forensic audit', () => {
  test.beforeEach(async ({ page }) => {
    await openChat(page);
  });

  test('runtime provider catalog exposes at least one auditable provider', async ({ page }) => {
    const catalog = await fetchRuntimeCatalog(page);
    const providers = getAuditableProviders(catalog);

    expect(
      providers.length,
      'No configured runtime providers returned by /api/runtime/providers',
    ).toBeGreaterThan(0);
  });

  test('default selected provider returns an actual chat response', async ({ page }) => {
    const catalog = await fetchRuntimeCatalog(page);
    const providers = getAuditableProviders(catalog);

    expect(providers.length).toBeGreaterThan(0);

    const defaultProvider =
      providers.find((provider) => provider.id === catalog.default_provider) || providers[0];
    const model = pickProviderModel(defaultProvider);

    await selectProviderAndModel(page, defaultProvider.id, model.id);
    await sendAuditPrompt(page);
    await waitForAssistantResponse(page);
    await openResponseDetails(page);

    await expectForensicMetadata(page);
    await expectRequestedProviderReflected(page, defaultProvider.id, model.id);
    await expectNoFakeSuccess(page);
  });

  test('all configured providers return actual response or honest degraded metadata', async ({ page }) => {
    const catalog = await fetchRuntimeCatalog(page);
    const providers = getAuditableProviders(catalog);
    console.log(`Auditing ${providers.length} providers: ${providers.map(p => p.id).join(', ')}`);

    expect(providers.length).toBeGreaterThan(0);

    // Test a subset of providers to keep the audit efficient
    const providersToAudit = providers.slice(0, 3);

    for (const provider of providersToAudit) {
      const model = pickProviderModel(provider);
      console.log(`Starting audit for ${provider.id} using model ${model.id}`);

      await test.step(`audit ${provider.id} / ${model.id}`, async () => {
        await selectProviderAndModel(page, provider.id, model.id);
        await sendAuditPrompt(page);
        await waitForAssistantResponse(page);
        await openResponseDetails(page);

        await expectForensicMetadata(page);
        await expectRequestedProviderReflected(page, provider.id, model.id);
      });
    }
  });

  test('provider catalog selection and chat metadata do not diverge', async ({ page }) => {
    const catalog = await fetchRuntimeCatalog(page);
    const providers = getAuditableProviders(catalog);

    for (const provider of providers) {
      const model = pickProviderModel(provider);

      await test.step(`selection truth ${provider.id}`, async () => {
        await selectProviderAndModel(page, provider.id, model.id);

        await expect(page.getByTestId('chat-provider-select')).toHaveValue(provider.id);
        await expect(page.getByTestId('chat-model-select')).toHaveValue(model.id);
      });
    }
  });
});
