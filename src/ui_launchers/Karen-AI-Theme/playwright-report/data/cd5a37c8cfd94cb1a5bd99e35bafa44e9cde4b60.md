# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: chat-runtime-forensic-mocked.spec.ts >> Chat runtime forensic mocked fallback states >> renders emergency unavailable honestly without fake model success
- Location: tests/e2e/chat-runtime-forensic-mocked.spec.ts:57:7

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: expect(locator).toBeVisible() failed

Locator: getByTestId('chat-root')
Expected: visible
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 30000ms
  - waiting for getByTestId('chat-root')

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e3]:
    - generic [ref=e4]:
      - img [ref=e5]
      - generic [ref=e15]: Welcome Back
      - generic [ref=e16]: Log in to continue to Karen AI
    - generic [ref=e17]:
      - generic [ref=e19]:
        - button "Email" [ref=e20] [cursor=pointer]
        - button "Username" [ref=e21] [cursor=pointer]
      - generic [ref=e23]:
        - generic [ref=e24]:
          - generic [ref=e25]: Email
          - textbox "Email" [ref=e26]:
            - /placeholder: m@example.com
        - generic [ref=e27]:
          - generic [ref=e28]:
            - generic [ref=e29]: Password
            - link "Forgot password?" [ref=e30] [cursor=pointer]:
              - /url: "#"
          - textbox "Password" [ref=e31]
        - button "Login" [ref=e32] [cursor=pointer]
        - generic [ref=e37]: Or continue with
        - button "Login with Google" [ref=e38] [cursor=pointer]
      - generic [ref=e39]:
        - text: Don't have an account?
        - link "Sign up" [ref=e40] [cursor=pointer]:
          - /url: "#"
  - region "Notifications (F8)":
    - list
  - button "Open Next.js Dev Tools" [ref=e46] [cursor=pointer]:
    - img [ref=e47]
  - alert [ref=e50]
```

# Test source

```ts
  1   | import { expect, Page, APIRequestContext, test } from '@playwright/test';
  2   | 
  3   | export type RuntimeProviderModel = {
  4   |   id: string;
  5   |   label?: string;
  6   |   name?: string;
  7   |   available?: boolean;
  8   |   default?: boolean;
  9   | };
  10  | 
  11  | export type RuntimeProvider = {
  12  |   id: string;
  13  |   label?: string;
  14  |   display_name?: string;
  15  |   enabled?: boolean;
  16  |   configured?: boolean;
  17  |   healthy?: boolean;
  18  |   allowed_for_current_user?: boolean;
  19  |   requires_api_key?: boolean;
  20  |   runtime_engine?: string;
  21  |   category?: string;
  22  |   models?: RuntimeProviderModel[];
  23  | };
  24  | 
  25  | export type RuntimeProviderCatalog = {
  26  |   providers: RuntimeProvider[];
  27  |   default_provider?: string;
  28  |   default_model?: string;
  29  |   fallback_order?: string[];
  30  | };
  31  | 
  32  | export async function fetchRuntimeCatalog(request: APIRequestContext): Promise<RuntimeProviderCatalog> {
  33  |   const response = await request.get('/api/runtime/providers');
  34  |   expect(response.ok(), `GET /api/runtime/providers failed: ${response.status()}`).toBeTruthy();
  35  |   return response.json();
  36  | }
  37  | 
  38  | export function getAuditableProviders(catalog: RuntimeProviderCatalog): RuntimeProvider[] {
  39  |   return (catalog.providers || []).filter((provider) => {
  40  |     const models = provider.models || [];
  41  |     return (
  42  |       provider.enabled !== false &&
  43  |       provider.configured !== false &&
  44  |       provider.allowed_for_current_user !== false &&
  45  |       models.length > 0
  46  |     );
  47  |   });
  48  | }
  49  | 
  50  | export function pickProviderModel(provider: RuntimeProvider): RuntimeProviderModel {
  51  |   const models = provider.models || [];
  52  |   const defaultModel = models.find((model) => model.default);
  53  |   return defaultModel || models[0];
  54  | }
  55  | 
  56  | export async function openChat(page: Page): Promise<void> {
  57  |   await page.goto('/');
> 58  |   await expect(page.getByTestId('chat-root')).toBeVisible({ timeout: 30_000 });
      |                                               ^ Error: expect(locator).toBeVisible() failed
  59  | }
  60  | 
  61  | export async function selectProviderAndModel(
  62  |   page: Page,
  63  |   providerId: string,
  64  |   modelId: string,
  65  | ): Promise<void> {
  66  |   const providerSelect = page.getByTestId('chat-provider-select');
  67  |   const modelSelect = page.getByTestId('chat-model-select');
  68  | 
  69  |   await expect(providerSelect).toBeVisible({ timeout: 15_000 });
  70  |   await providerSelect.selectOption(providerId);
  71  | 
  72  |   await expect(modelSelect).toBeVisible({ timeout: 15_000 });
  73  |   await modelSelect.selectOption(modelId);
  74  | }
  75  | 
  76  | export async function sendAuditPrompt(page: Page): Promise<void> {
  77  |   await page.getByTestId('chat-input').fill(
  78  |     'Reply with exactly this phrase and nothing else: KAREN_RUNTIME_AUDIT_OK',
  79  |   );
  80  |   await page.getByTestId('chat-submit').click();
  81  | }
  82  | 
  83  | export async function waitForAssistantResponse(page: Page): Promise<void> {
  84  |   await expect(page.getByTestId('chat-message-assistant').last()).toBeVisible({
  85  |     timeout: 120_000,
  86  |   });
  87  | 
  88  |   const text = await page.getByTestId('chat-message-assistant').last().innerText();
  89  |   expect(text.trim().length, 'Assistant response was empty').toBeGreaterThan(0);
  90  | }
  91  | 
  92  | export async function openResponseDetails(page: Page): Promise<void> {
  93  |   const toggle = page.getByTestId('chat-response-details-toggle').last();
  94  |   await expect(toggle).toBeVisible({ timeout: 20_000 });
  95  |   await toggle.click();
  96  | 
  97  |   await expect(page.getByTestId('chat-response-details-panel').last()).toBeVisible({
  98  |     timeout: 10_000,
  99  |   });
  100 | }
  101 | 
  102 | export async function expectForensicMetadata(page: Page): Promise<void> {
  103 |   await expect(page.getByTestId('chat-requested-provider').last()).toBeVisible();
  104 |   await expect(page.getByTestId('chat-requested-model').last()).toBeVisible();
  105 |   await expect(page.getByTestId('chat-actual-provider').last()).toBeVisible();
  106 |   await expect(page.getByTestId('chat-actual-model').last()).toBeVisible();
  107 |   await expect(page.getByTestId('chat-runtime-engine').last()).toBeVisible();
  108 |   await expect(page.getByTestId('chat-response-source').last()).toBeVisible();
  109 |   await expect(page.getByTestId('chat-fallback-level').last()).toBeVisible();
  110 |   await expect(page.getByTestId('chat-correlation-id').last()).toBeVisible();
  111 | 
  112 |   const actualProvider = await page.getByTestId('chat-actual-provider').last().innerText();
  113 |   const runtimeEngine = await page.getByTestId('chat-runtime-engine').last().innerText();
  114 |   const correlationId = await page.getByTestId('chat-correlation-id').last().innerText();
  115 | 
  116 |   expect(actualProvider.trim(), 'Actual provider missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
  117 |   expect(runtimeEngine.trim(), 'Runtime engine missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
  118 |   expect(correlationId.trim(), 'Correlation ID missing').not.toMatch(/^(n\/a|none|unknown)?$/i);
  119 | }
  120 | 
  121 | export async function expectRequestedProviderReflected(
  122 |   page: Page,
  123 |   providerId: string,
  124 |   modelId: string,
  125 | ): Promise<void> {
  126 |   const requestedProvider = await page.getByTestId('chat-requested-provider').last().innerText();
  127 |   const requestedModel = await page.getByTestId('chat-requested-model').last().innerText();
  128 | 
  129 |   expect(requestedProvider.toLowerCase()).toContain(providerId.toLowerCase().replace('builtin_', '').split('_')[0]);
  130 |   expect(requestedModel.length).toBeGreaterThan(0);
  131 | 
  132 |   if (modelId !== 'auto') {
  133 |     expect(requestedModel.toLowerCase()).toContain(modelId.toLowerCase().split('/').pop()!.slice(0, 8));
  134 |   }
  135 | }
  136 | 
  137 | export async function expectNoFakeSuccess(page: Page): Promise<void> {
  138 |   const assistantText = await page.getByTestId('chat-message-assistant').last().innerText();
  139 | 
  140 |   const forbiddenFakeSuccess = [
  141 |     "I'm currently experiencing some technical difficulties",
  142 |     "can only provide limited responses",
  143 |     "try again later when the system is fully operational",
  144 |   ];
  145 | 
  146 |   for (const phrase of forbiddenFakeSuccess) {
  147 |     expect(
  148 |       assistantText,
  149 |       `Response looks like hardcoded degraded text: ${phrase}`,
  150 |     ).not.toContain(phrase);
  151 |   }
  152 | }
  153 | 
```