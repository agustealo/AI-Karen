import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright Configuration for Karen E2E Tests
 * 
 * Tests Gemini live responses and verifies no logout bugs
 */

export default defineConfig({
  testDir: './',
  testMatch: '**/*.spec.ts',
  
  // Test timeout
  timeout: 60000, // 60 seconds per test
  
  // Expect timeout
  expect: {
    timeout: 10000, // 10 seconds for assertions
  },
  
  // Run tests in parallel
  fullyParallel: false, // Run sequentially to avoid race conditions
  
  // Fail fast on CI
  forbidOnly: !!process.env.CI,
  
  // Retry on CI
  retries: process.env.CI ? 2 : 0,
  
  // Workers
  workers: process.env.CI ? 1 : 1,
  
  // Reporter
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],
  
  // Shared settings
  use: {
    // Base URL
    baseURL: process.env.KAREN_BASE_URL || 'http://localhost:8010',
    
    // Browser options
    headless: process.env.CI ? true : false,
    
    // Viewport
    viewport: { width: 1280, height: 720 },
    
    // Screenshots
    screenshot: 'only-on-failure',
    
    // Videos
    video: 'retain-on-failure',
    
    // Trace
    trace: 'retain-on-failure',
    
    // Action timeout
    actionTimeout: 15000,
    
    // Navigation timeout
    navigationTimeout: 30000,
  },
  
  // Projects for different browsers
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    
    // Uncomment to test on other browsers
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],
  
  // Web server (optional - if you want Playwright to start the server)
  // webServer: {
  //   command: 'npm run dev',
  //   url: 'http://localhost:3000',
  //   reuseExistingServer: !process.env.CI,
  //   timeout: 120000,
  // },
});

// Made with Bob
