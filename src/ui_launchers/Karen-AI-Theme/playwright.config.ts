import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for AI-Karen E2E tests.
 *
 * Canonical browser tests currently live in both `tests/e2e` and the
 * transitional top-level `e2e` directory. Keep discovery centralized here so
 * CI cannot silently omit first-run coverage while that directory migration is
 * completed.
 */
const liveGenerationAudit = process.env.KAREN_CHAT_GENERATION_LIVE_ACCEPTANCE === 'true';

export default defineConfig({
  testDir: '.',
  testMatch: ['tests/e2e/**/*.spec.ts', 'e2e/**/*.spec.ts'],
  timeout: 300000,
  expect: {
    timeout: 60000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: liveGenerationAudit ? 0 : process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: liveGenerationAudit ? [['list']] : 'html',
  use: {
    baseURL: liveGenerationAudit ? process.env.KAREN_BASE_URL : 'http://localhost:3000',
    trace: liveGenerationAudit ? 'off' : 'on-first-retry',
    screenshot: liveGenerationAudit ? 'off' : 'only-on-failure',
    video: liveGenerationAudit ? 'off' : 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
    },
  ],

  webServer: liveGenerationAudit ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 300000,
  },
});
