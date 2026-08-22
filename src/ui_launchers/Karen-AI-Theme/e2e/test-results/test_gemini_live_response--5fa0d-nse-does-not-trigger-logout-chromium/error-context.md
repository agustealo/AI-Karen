# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: test_gemini_live_response.spec.ts >> Gemini Live Response Tests >> Gemini response does not trigger logout
- Location: test_gemini_live_response.spec.ts:140:7

# Error details

```
TimeoutError: page.waitForURL: Timeout 15000ms exceeded.
=========================== logs ===========================
waiting for navigation until "load"
============================================================
```

# Test source

```ts
  1   | /**
  2   |  * Playwright E2E Test: Gemini Live Response Verification
  3   |  * 
  4   |  * Tests that Gemini provider returns live responses (not fallback)
  5   |  * when properly configured with API key.
  6   |  */
  7   | 
  8   | import { test, expect, Page } from '@playwright/test';
  9   | 
  10  | // Configuration
  11  | const BASE_URL = process.env.KAREN_BASE_URL || 'http://localhost:8010';
  12  | const API_URL = process.env.KAREN_API_URL || 'http://localhost:8000';
  13  | const LOGIN_EMAIL = 'admin@kari.ai';
  14  | const LOGIN_PASSWORD = 'Admin@123!';
  15  | 
  16  | test.describe('Gemini Live Response Tests', () => {
  17  |   let page: Page;
  18  | 
  19  |   test.beforeEach(async ({ page: testPage }) => {
  20  |     page = testPage;
  21  |     
  22  |     // Navigate to login page
  23  |     await page.goto(BASE_URL);
  24  |     
  25  |     // Wait for login form
  26  |     await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 10000 });
  27  |     
  28  |     // Login
  29  |     await page.fill('input[type="email"], input[name="email"]', LOGIN_EMAIL);
  30  |     await page.fill('input[type="password"], input[name="password"]', LOGIN_PASSWORD);
  31  |     await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")');
  32  |     
  33  |     // Wait for redirect to dashboard after login (chat is embedded in dashboard)
  34  |     // Use waitForURL with a more flexible check
  35  |     try {
> 36  |       await page.waitForURL(/\/dashboard/, { timeout: 15000 });
      |                  ^ TimeoutError: page.waitForURL: Timeout 15000ms exceeded.
  37  |     } catch (e) {
  38  |       // If already on dashboard (from previous test), that's fine
  39  |       if (!page.url().includes('/dashboard')) {
  40  |         throw e;
  41  |       }
  42  |     }
  43  |     
  44  |     console.log('✅ Logged in successfully, waiting for chat interface...');
  45  |     
  46  |     // Wait for page to fully load including dynamic content
  47  |     await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
  48  |     
  49  |     // Wait additional time for React/Next.js hydration and dynamic components
  50  |     await page.waitForTimeout(5000);
  51  |     
  52  |     // Wait for Karen chat input to load (embedded in dashboard)
  53  |     // Input element: <input placeholder="Ask Karen anything..." type="text">
  54  |     await page.waitForSelector('input[placeholder="Ask Karen anything..."]', {
  55  |       timeout: 45000,
  56  |       state: 'visible'
  57  |     });
  58  |     
  59  |     console.log('✅ Chat interface loaded');
  60  |   });
  61  | 
  62  |   test('Gemini provider returns live response with correct metadata', async () => {
  63  |     // Open provider settings modal
  64  |     const settingsButton = page.locator('button[aria-label="Open model and provider settings"]');
  65  |     if (await settingsButton.count() > 0) {
  66  |       await settingsButton.click();
  67  |       console.log('✅ Opened provider settings modal');
  68  |       
  69  |       // Wait for modal content
  70  |       await page.waitForSelector('text=AI Provider Settings');
  71  |       
  72  |       // Find Gemini in the sidebar and click it
  73  |       // The label is likely "Gemini" or "Google Gemini"
  74  |       const geminiOption = page.locator('button:has-text("Gemini")').first();
  75  |       if (await geminiOption.count() > 0) {
  76  |         await geminiOption.click();
  77  |         console.log('✅ Selected Gemini in modal sidebar');
  78  |         
  79  |         // Click Apply
  80  |         await page.click('button:has-text("Apply Selection"), button:has-text("Apply")');
  81  |         console.log('✅ Clicked Apply');
  82  |         
  83  |         // Wait for modal to close
  84  |         await page.waitForSelector('text=AI Provider Settings', { state: 'hidden' });
  85  |         await page.waitForTimeout(1000);
  86  |       } else {
  87  |         console.warn('⚠️ Gemini option not found in modal');
  88  |         await page.keyboard.press('Escape');
  89  |       }
  90  |     }
  91  | 
  92  |     // Type test message
  93  |     const messageInput = page.locator('input[placeholder="Ask Karen anything..."]').first();
  94  |     const testPrompt = 'Say "Gemini live response test passed" and nothing else.';
  95  |     await messageInput.fill(testPrompt);
  96  |     
  97  |     // Count existing messages to ensure we pick up the new one
  98  |     const initialMessageCount = await page.locator('.bg-card').count();
  99  |     
  100 |     // Send message
  101 |     await page.keyboard.press('Enter');
  102 |     console.log('✅ Sent test message');
  103 | 
  104 |     // Wait for a NEW assistant response to appear
  105 |     console.log(`Waiting for assistant message count to exceed ${initialMessageCount}...`);
  106 |     await page.waitForFunction(
  107 |       (count) => document.querySelectorAll('.bg-card').length > count,
  108 |       initialMessageCount,
  109 |       { timeout: 60000 }
  110 |     );
  111 |     
  112 |     // Wait for streaming to finish (prose p appears)
  113 |     await page.waitForSelector('.bg-card .prose p, .bg-card [class*="prose"] p', { timeout: 15000 });
  114 |     
  115 |     console.log('✅ Received assistant response');
  116 | 
  117 |     // Get the response text
  118 |     const messageText = await page.locator('.bg-card .prose p, .bg-card [class*="prose"] p').last().textContent();
  119 |     console.log('Response text:', messageText);
  120 | 
  121 |     // Verify response is not the prompt (echoing)
  122 |     expect(messageText?.toLowerCase()).not.toContain('say "');
  123 |     expect(messageText).toBeTruthy();
  124 | 
  125 |     // Check metadata
  126 |     const metadataButton = page.locator('button:has-text("Show response details"), button:has-text("Details")');
  127 |     if (await metadataButton.count() > 0) {
  128 |       await metadataButton.last().click();
  129 |       await page.waitForTimeout(1000);
  130 | 
  131 |       // Verify metadata shows Gemini
  132 |       const bodyText = await page.textContent('body');
  133 |       expect(bodyText?.toLowerCase()).toContain('gemini');
  134 |       expect(bodyText?.toLowerCase()).not.toContain('gpt2');
  135 |       
  136 |       console.log('✅ Metadata verified Gemini provider');
```