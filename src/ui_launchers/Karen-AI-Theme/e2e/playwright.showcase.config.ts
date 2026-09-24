import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.KAREN_SHOWCASE_BASE_URL || "http://localhost:8010";

export default defineConfig({
  testDir: "./showcase",
  testMatch: "**/*.showcase.ts",
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    headless: true,
    viewport: { width: 1600, height: 1000 },
    colorScheme: "dark",
    screenshot: "off",
    video: "off",
    trace: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
});
