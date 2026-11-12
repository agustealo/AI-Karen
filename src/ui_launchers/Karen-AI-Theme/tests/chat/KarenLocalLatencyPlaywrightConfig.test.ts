import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * KCON-776: evaluate the actual Playwright config under each supported mode.
 * The canonical benchmark uses this config; no browser, model, network
 * request, production credential or duplicated runner is involved.
 */
async function loadBrowserConfig(
  mode: "local" | "terminal" | "ci",
  captureVideo = false,
) {
  vi.stubEnv("KAREN_LOCAL_LATENCY_BENCHMARK", mode === "local" ? "1" : "0");
  vi.stubEnv("CI", mode === "ci" ? "true" : "");
  vi.stubEnv("KAREN_UX_IDENTITY_REPLAY", "false");
  vi.stubEnv("KAREN_SEARCH_ACCEPTANCE_REQUIRED", "false");
  vi.stubEnv("KAREN_E2E_CAPTURE_VIDEO", captureVideo ? "true" : "false");

  // Import *after* selecting the environment to test evaluation-time
  // config authority, rather than replaying the implementation in a mock.
  vi.resetModules();
  const { default: config } = await import("../../e2e/playwright.config");
  return config;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("KCON-776 real local latency Playwright configuration", () => {
  it("runs headless and serially with zero retries and no credential capture", async () => {
    const config = await loadBrowserConfig("local", true);

    expect(config.use?.headless).toBe(true);
    expect(config.retries).toBe(0);
    expect(config.workers).toBe(1);
    expect(config.fullyParallel).toBe(false);
    expect(config.forbidOnly).toBe(false);
    expect(config.use?.screenshot).toBe("off");
    expect(config.use?.video).toBe("off");
    expect(config.use?.trace).toBe("off");
    expect(config.projects?.map(project => project.name)).toEqual(["chromium"]);
    expect(config.reporter).toEqual(expect.arrayContaining([
      ["json", { outputFile: "test-results.json" }],
    ]));
  });

  it("preserves ordinary terminal acceptance defaults", async () => {
    const config = await loadBrowserConfig("terminal");

    expect(config.use?.headless).toBe(false);
    expect(config.retries).toBe(0);
    expect(config.workers).toBe(1);
    expect(config.forbidOnly).toBe(false);
    expect(config.use?.screenshot).toBe("only-on-failure");
    expect(config.use?.video).toBe("retain-on-failure");
    expect(config.use?.trace).toBe("retain-on-failure");
  });

  it("preserves normal CI retry, headless and focused-test rules", async () => {
    const config = await loadBrowserConfig("ci");

    expect(config.use?.headless).toBe(true);
    expect(config.retries).toBe(2);
    expect(config.forbidOnly).toBe(true);
    expect(config.use?.screenshot).toBe("only-on-failure");
    expect(config.use?.video).toBe("retain-on-failure");
    expect(config.use?.trace).toBe("retain-on-failure");
  });
});
