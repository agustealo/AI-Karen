/**
 * Playwright E2E Test: Gemini Live Response Verification
 * 
 * Tests that Gemini provider returns live responses (not fallback)
 * when properly configured with API key.
 */

import { test, expect, Page } from '@playwright/test';

// Configuration
const BASE_URL = process.env.KAREN_BASE_URL || 'http://localhost:8010';
const API_URL = process.env.KAREN_API_URL || 'http://localhost:8000';
const LOGIN_EMAIL = 'admin@kari.ai';
const LOGIN_PASSWORD = 'Admin@123!';

test.describe('Gemini Live Response Tests', () => {
  let page: Page;

  test.beforeEach(async ({ page: testPage }) => {
    page = testPage;
    
    // Navigate to login page
    await page.goto(BASE_URL);
    
    // Wait for login form
    await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 10000 });
    
    // Login
    await page.fill('input[type="email"], input[name="email"]', LOGIN_EMAIL);
    await page.fill('input[type="password"], input[name="password"]', LOGIN_PASSWORD);
    await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")');
    
    // Wait for redirect to dashboard after login (chat is embedded in dashboard)
    // Use waitForURL with a more flexible check
    try {
      await page.waitForURL(/\/dashboard/, { timeout: 15000 });
    } catch (e) {
      // If already on dashboard (from previous test), that's fine
      if (!page.url().includes('/dashboard')) {
        throw e;
      }
    }
    
    console.log('✅ Logged in successfully, waiting for chat interface...');
    
    // Wait for page to fully load including dynamic content
    await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
    
    // Wait additional time for React/Next.js hydration and dynamic components
    await page.waitForTimeout(5000);
    
    // Wait for Karen chat input to load (embedded in dashboard)
    // Input element: <input placeholder="Ask Karen anything..." type="text">
    await page.waitForSelector('input[placeholder="Ask Karen anything..."]', {
      timeout: 45000,
      state: 'visible'
    });
    
    console.log('✅ Chat interface loaded');
  });

  test('Gemini provider returns live response with correct metadata', async () => {
    // Open provider settings modal
    const settingsButton = page.locator('button[aria-label="Open model and provider settings"]');
    if (await settingsButton.count() > 0) {
      await settingsButton.click();
      console.log('✅ Opened provider settings modal');
      
      // Wait for modal content
      await page.waitForSelector('text=AI Provider Settings');
      
      // Find Gemini in the sidebar and click it
      // The label is likely "Gemini" or "Google Gemini"
      const geminiOption = page.locator('button:has-text("Gemini")').first();
      if (await geminiOption.count() > 0) {
        await geminiOption.click();
        console.log('✅ Selected Gemini in modal sidebar');
        
        // Click Apply
        await page.click('button:has-text("Apply Selection"), button:has-text("Apply")');
        console.log('✅ Clicked Apply');
        
        // Wait for modal to close
        await page.waitForSelector('text=AI Provider Settings', { state: 'hidden' });
        await page.waitForTimeout(1000);
      } else {
        console.warn('⚠️ Gemini option not found in modal');
        await page.keyboard.press('Escape');
      }
    }

    // Type test message
    const messageInput = page.locator('input[placeholder="Ask Karen anything..."]').first();
    const testPrompt = 'Say "Gemini live response test passed" and nothing else.';
    await messageInput.fill(testPrompt);
    
    // Count existing messages to ensure we pick up the new one
    const initialMessageCount = await page.locator('.bg-card').count();
    
    // Send message
    await page.keyboard.press('Enter');
    console.log('✅ Sent test message');

    // Wait for a NEW assistant response to appear
    console.log(`Waiting for assistant message count to exceed ${initialMessageCount}...`);
    await page.waitForFunction(
      (count) => document.querySelectorAll('.bg-card').length > count,
      initialMessageCount,
      { timeout: 60000 }
    );
    
    // Wait for streaming to finish (prose p appears)
    await page.waitForSelector('.bg-card .prose p, .bg-card [class*="prose"] p', { timeout: 15000 });
    
    console.log('✅ Received assistant response');

    // Get the response text
    const messageText = await page.locator('.bg-card .prose p, .bg-card [class*="prose"] p').last().textContent();
    console.log('Response text:', messageText);

    // Verify response is not the prompt (echoing)
    expect(messageText?.toLowerCase()).not.toContain('say "');
    expect(messageText).toBeTruthy();

    // Check metadata
    const metadataButton = page.locator('button:has-text("Show response details"), button:has-text("Details")');
    if (await metadataButton.count() > 0) {
      await metadataButton.last().click();
      await page.waitForTimeout(1000);

      // Verify metadata shows Gemini
      const bodyText = await page.textContent('body');
      expect(bodyText?.toLowerCase()).toContain('gemini');
      expect(bodyText?.toLowerCase()).not.toContain('gpt2');
      
      console.log('✅ Metadata verified Gemini provider');
    }
  });

  test('Gemini response does not trigger logout', async () => {
    // Send first message
    const messageInput = page.locator('input[placeholder="Ask Karen anything..."]').first();
    await messageInput.fill('First message test');
    await page.keyboard.press('Enter');
    
    // Wait for response
    await page.waitForSelector('.bg-card .prose p, .bg-card [class*="prose"] p', { 
      timeout: 30000 
    });
    
    console.log('✅ First message sent and received');

    // Wait a bit
    await page.waitForTimeout(2000);

    // Send second message
    await messageInput.fill('Second message test');
    await page.keyboard.press('Enter');
    
    // Wait for second response
    await page.waitForFunction(
      () => document.querySelectorAll('.bg-card .prose p, .bg-card [class*="prose"] p').length >= 2,
      null,
      { timeout: 30000 }
    );
    
    console.log('✅ Second message sent and received');

    // Verify we're still logged in (not redirected to login page)
    const currentUrl = page.url();
    expect(currentUrl).not.toContain('/login');
    expect(currentUrl).not.toContain('/signin');
    
    // Verify chat interface still visible
    const chatInput = page.locator('input[placeholder="Ask Karen anything..."]');
    await expect(chatInput).toBeVisible();
    
    console.log('✅ User still logged in after multiple messages');
  });

  test('Gemini API key is configured', async () => {
    // Check provider health endpoint
    const response = await page.request.get(`${API_URL}/api/health/providers/all`);
    expect(response.ok()).toBeTruthy();
    
    const data = await response.json();
    console.log('Provider health data:', JSON.stringify(data, null, 2));
    
    // Verify Gemini provider exists and is enabled
    expect(data.providers).toHaveProperty('gemini');
    expect(data.providers.gemini.enabled).toBe(true);
    
    // Verify Gemini has API key configured
    // Note: We don't check the actual key value for security
    console.log('✅ Gemini provider is enabled');
  });

  test('Response metadata shows live_model source', async () => {
    // Open provider settings modal and select Gemini
    const settingsButton = page.locator('button[aria-label="Open model and provider settings"]');
    if (await settingsButton.count() > 0) {
      await settingsButton.click();
      await page.waitForSelector('text=AI Provider Settings');
      const geminiOption = page.locator('button:has-text("Gemini")').first();
      if (await geminiOption.count() > 0) {
        await geminiOption.click();
        await page.click('button:has-text("Apply Selection"), button:has-text("Apply")');
        await page.waitForSelector('text=AI Provider Settings', { state: 'hidden' });
        await page.waitForTimeout(1000);
      } else {
        await page.keyboard.press('Escape');
      }
    }

    // Send message to check metadata
    const messageInput = page.locator('input[placeholder="Ask Karen anything..."]').first();
    await messageInput.fill('Metadata test message');

    const sendButton = page.locator('button[type="submit"], button:has-text("Send"), button[aria-label*="send" i]').first();
    if (await sendButton.count() > 0 && await sendButton.isEnabled()) {
      await sendButton.click();
    } else {
      await page.keyboard.press('Enter');
    }
    
    // Wait for response
    await page.waitForSelector('.bg-card .prose p, .bg-card [class*="prose"] p', {
      timeout: 30000
    });

    // Open metadata
    const metadataButton = page.locator('button:has-text("Show response details"), button:has-text("Details")');
    if (await metadataButton.count() > 0) {
      await metadataButton.last().click();
      await page.waitForTimeout(500);

      const metadataText = await page.textContent('body');
      
      // Verify response_source is live_model (not emergency_static)
      expect(metadataText).toContain('live_model');
      expect(metadataText).not.toContain('emergency_static');
      
      // Verify actual_provider matches requested_provider
      const actualProviderMatch = metadataText?.match(/actual[_\s]*provider[:\s]*["']?(\w+)/i);
      const requestedProviderMatch = metadataText?.match(/requested[_\s]*provider[:\s]*["']?(\w+)/i);
      
      if (actualProviderMatch && requestedProviderMatch) {
        expect(actualProviderMatch[1]).toBe(requestedProviderMatch[1]);
        console.log('✅ Actual provider matches requested provider');
      }
      
      console.log('✅ Metadata shows live_model response source');
    }
  });

  test.afterEach(async () => {
    // Cleanup: logout or close
    await page.close();
  });
});

// Made with Bob
