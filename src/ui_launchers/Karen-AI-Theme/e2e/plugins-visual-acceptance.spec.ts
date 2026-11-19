import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KUI-PLUGINS: real, read-only Plugins & Tools browser acceptance.
 *
 * Reuses the canonical authenticated plugin registry at /api/extensions/list.
 * No route mocks, fabricated plugin status, lifecycle mutations or privileged
 * install calls. Captures only opt-in, sanitized display evidence.
 *
 * Opt-in: KAREN_PLUGINS_VISUAL_ACCEPTANCE=true
 * Local: KAREN_LOCAL_CHAT_ACCEPTANCE=1 + loopback KAREN_BASE_URL
 * Auth: KAREN_UX_EMAIL and KAREN_UX_PASSWORD (dedicated test identity)
 * Capture: KAREN_PLUGINS_SANITIZED_CAPTURE=true on an approved sanitized host.
 */
const enabled = process.env.KAREN_PLUGINS_VISUAL_ACCEPTANCE === "true";
const sanitizedCapture = process.env.KAREN_PLUGINS_SANITIZED_CAPTURE === "true";
const approvedUrl = process.env.KAREN_BASE_URL;
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;

const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

type PluginEntry = {
  name: string;
  status: string;
  version: string;
  capabilities?: {
    provides_ui?: boolean;
    communication_channel?: boolean;
  };
  has_component?: boolean;
  ui?: { has_component?: boolean };
  ui_entry_points?: unknown[];
};

test.use({ trace: "off", video: "off", screenshot: "off", colorScheme: "dark" });

function validateOrigin(): URL {
  if (!approvedUrl) throw new Error("KAREN_BASE_URL is required");
  const target = new URL(approvedUrl);
  if (target.username || target.password || target.pathname !== "/" ||
      target.search || target.hash) {
    throw new Error("Refusing credentials for non-origin URL");
  }
  const local = target.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(target.hostname) &&
    !!target.port && process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
  const release = target.protocol === "https:" && target.port === "";
  if (!local && !release) throw new Error("Only approved HTTPS or opted-in local loopback is allowed");
  return target;
}

function parsePluginRegistry(raw: unknown): PluginEntry[] {
  const value = Array.isArray(raw) ? raw : raw && typeof raw === "object"
    ? (raw as Record<string, unknown>).plugins ??
      (raw as Record<string, unknown>).extensions
    : undefined;
  if (!Array.isArray(value) || !value.every((entry): entry is PluginEntry =>
    entry !== null && typeof entry === "object" &&
    typeof entry.name === "string" && entry.name.length > 0 &&
    typeof entry.version === "string" && typeof entry.status === "string")) {
    throw new Error("Real plugin catalog violates the backend registry contract");
  }
  return value;
}

function hasDeclaredUi(entry: PluginEntry): boolean {
  return entry.capabilities?.provides_ui === true ||
    entry.ui?.has_component === true ||
    entry.has_component === true ||
    (Array.isArray(entry.ui_entry_points) && entry.ui_entry_points.length > 0);
}

async function openPluginOverview(page: Page): Promise<void> {
  let navigation = page.getByRole("button", { name: "Tools & plugins", exact: true });
  if (!(await navigation.last().isVisible().catch(() => false))) {
    const toggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(toggle).toBeVisible();
    await toggle.click();
    navigation = page.getByRole("button", { name: "Tools & plugins", exact: true });
  }
  await expect(navigation.last()).toBeVisible();
  await navigation.last().click();
  await expect(page.getByTestId("plugins-overview")).toBeVisible({ timeout: 30_000 });
}

test("KUI-PLUGINS: authenticated catalog, five viewport layouts, and keyboard controls", async (
  { page }, info: TestInfo,
) => {
  test.skip(!enabled, "Enable with KAREN_PLUGINS_VISUAL_ACCEPTANCE=true");
  test.setTimeout(6 * 60_000);
  if (!email || !password) {
    throw new Error("Dedicated sanitized KAREN_UX_EMAIL and KAREN_UX_PASSWORD required");
  }
  const target = validateOrigin();
  await page.setViewportSize(viewports[0]);

  // Listen *before* sign-in because PluginRegistryProvider fetches on
  // authenticated dashboard mount. No re-fetch endpoint or test-only hook.
  const catalogRequest = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === "/api/extensions/list" &&
      response.request().method() === "GET";
  }, { timeout: 45_000 });

  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });
  expect(new URL(page.url()).origin).toBe(target.origin);
  const response = await catalogRequest;
  expect(response.status(), "Plugin registry requires a real authenticated 200").toBe(200);
  const entries = parsePluginRegistry(await response.json());

  await openPluginOverview(page);
  const root = page.getByTestId("plugins-overview");
  await expect(root.getByRole("heading", { level: 1, name: "Plugins & Tools" })).toBeVisible();
  await expect(root.getByTestId("plugin-count")).toHaveText(String(entries.length));
  await expect(root.getByTestId("plugin-ui-count")).toHaveText(
    String(entries.filter(hasDeclaredUi).length),
  );
  await expect(root.getByTestId("plugin-channel-count")).toHaveText(
    String(entries.filter(entry => entry.capabilities?.communication_channel === true).length),
  );
  await expect(root.getByTestId("plugin-integration-card")).toHaveCount(entries.length);

  // The route is an existing governed installation workspace, not a new
  // privileged installer or an automation command hidden behind the hero.
  const installLink = root.getByRole("link", { name: "Upload and install a plugin" });
  await expect(installLink).toHaveAttribute("href", "/plugins");

  const styling = await root.evaluate(element => {
    const css = getComputedStyle(element);
    const heading = element.querySelector(".kari-display");
    return {
      canvas: css.getPropertyValue("--kari-canvas").trim(),
      panel: css.getPropertyValue("--kari-panel").trim(),
      font: css.fontFamily,
      headingFont: heading ? getComputedStyle(heading).fontFamily : "",
    };
  });
  expect(styling.canvas).toBe("#070708");
  expect(styling.panel).toBe("#0d0e0f");
  expect(styling.font).toMatch(/Inter/i);
  expect(styling.headingFont).toMatch(/Manrope/i);

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(root).toBeVisible();

    // Inspect real geometry after responsive transition. Do not relax the
    // document-width constraint to conceal sideways overflow.
    await expect.poll(async () => root.evaluate(element => {
      const r = element.getBoundingClientRect();
      return r.left >= -1 &&
        r.right <= document.documentElement.clientWidth + 1;
    }), { timeout: 5000 }).toBe(true);

    const geometry = await root.evaluate(element => {
      const hero = element.querySelector("header");
      if (!hero) return null;
      const rootRect = element.getBoundingClientRect();
      const heroRect = hero.getBoundingClientRect();
      return {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        rootLeft: rootRect.left,
        rootRight: rootRect.right,
        heroLeft: heroRect.left,
        heroRight: heroRect.right,
      };
    });
    expect(geometry).not.toBeNull();
    if (!geometry) throw new Error("Plugin workspace geometry unavailable");
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
    expect(geometry.rootLeft).toBeGreaterThanOrEqual(-1);
    expect(geometry.rootRight).toBeLessThanOrEqual(geometry.clientWidth + 1);
    expect(geometry.heroLeft).toBeGreaterThanOrEqual(-1);
    expect(geometry.heroRight).toBeLessThanOrEqual(geometry.clientWidth + 1);

    await expect(installLink).toBeVisible();
    await expect(installLink).toBeEnabled();

    if (sanitizedCapture) {
      await info.attach("plugins-sanitized-" + viewport.width + "x" + viewport.height, {
        body: await root.screenshot({ animations: "disabled" }),
        contentType: "image/png",
      });
    }
  }

  // Reach the install link using real Tab traversal, not programmatic focus.
  await page.setViewportSize(viewports[0]);
  await root.getByRole("heading", { level: 1 }).click();
  let reachedInstallLink = false;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await page.keyboard.press("Tab");
    if (await installLink.evaluate(element => element === document.activeElement)) {
      reachedInstallLink = true;
      break;
    }
  }
  expect(reachedInstallLink, "Governed install navigation must be keyboard reachable").toBe(true);
  await expect(installLink).toBeFocused();

  // This suite never clicks an enable, disable, install or delete operation.
});
