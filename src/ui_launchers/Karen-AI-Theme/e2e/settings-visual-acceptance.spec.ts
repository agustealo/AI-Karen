import { type Page, type TestInfo } from "@playwright/test";
import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KUI-SETTINGS: opt-in, real-account KARI OS Settings acceptance.
 *
 * No API interception, fake configuration values, credentials in reports,
 * default screenshots, videos, or Playwright traces. Verify against an
 * approved sanitized account and a reachable KAREN runtime.
 */
const enabled = process.env.KAREN_SETTINGS_VISUAL_ACCEPTANCE === "true";
const capture = process.env.KAREN_SETTINGS_SANITIZED_CAPTURE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

test.use({ trace: "off", screenshot: "off", video: "off", colorScheme: "dark" });

function approvedOrigin(): URL {
  const configured = process.env.KAREN_BASE_URL;
  if (!configured) throw new Error("KAREN_BASE_URL must be an approved origin");
  const target = new URL(configured);
  if (target.username || target.password || target.pathname !== "/" ||
      target.search || target.hash) {
    throw new Error("Credentials require an unadorned approved origin");
  }
  const local = target.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(target.hostname) &&
    Boolean(target.port) && process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
  const release = target.protocol === "https:" && !target.port;
  if (!local && !release) throw new Error("Refusing unapproved credential origin");
  return target;
}

async function signIn(page: Page): Promise<void> {
  if (!email || !password) {
    throw new Error("Dedicated sanitized KAREN_UX_EMAIL and KAREN_UX_PASSWORD required");
  }
  const origin = approvedOrigin();
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });
  expect(new URL(page.url()).origin).toBe(origin.origin);
}

async function openFullPageSettings(page: Page): Promise<void> {
  let navigation = page.getByRole("button", { name: "Application Settings", exact: true });
  if (!await navigation.last().isVisible().catch(() => false)) {
    const toggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(toggle).toBeVisible();
    await toggle.click();
    navigation = page.getByRole("button", { name: "Application Settings", exact: true });
  }
  await expect(navigation.last()).toBeVisible();
  await navigation.last().click();
  await expect(page.getByTestId("karen-settings-workspace")).toBeVisible();
}

async function checkTheme(root: ReturnType<Page["getByTestId"]>): Promise<void> {
  const values = await root.evaluate(element => ({
    canvas: getComputedStyle(element).getPropertyValue("--kari-canvas").trim(),
    panel: getComputedStyle(element).getPropertyValue("--kari-panel").trim(),
    font: getComputedStyle(element).fontFamily,
  }));
  expect(values.canvas).toBe("#070708");
  expect(values.panel).toBe("#0d0e0f");
  expect(values.font).toMatch(/Inter/i);
}

async function checkGeometry(
  root: ReturnType<Page["getByTestId"]>,
  stacked: boolean,
): Promise<void> {
  // Radix Sheet slides in from the right; avoid sampling its transformed
  // bounding box before the real drawer has finished entering the viewport.
  // Poll the actual geometry rather than sleeping or widening the tolerance.
  await expect.poll(async () => root.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return bounds.left >= -1 &&
      bounds.right <= document.documentElement.clientWidth + 1;
  }), {
    timeout: 5_000,
    message: "Settings workspace must settle fully inside the viewport",
  }).toBe(true);
  const geometry = await root.evaluate(element => {
    const nav = element.querySelector(".karen-settings-section-nav");
    const panel = element.querySelector(".karen-settings-active");
    const categories = element.querySelector(".karen-settings-categories");
    if (!nav || !panel || !categories) return null;
    const a = nav.getBoundingClientRect();
    const b = panel.getBoundingClientRect();
    const c = categories.getBoundingClientRect();
    const r = element.getBoundingClientRect();
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      rootLeft: r.left, rootRight: r.right,
      navLeft: a.left, navRight: a.right, navBottom: a.bottom,
      panelLeft: b.left, panelRight: b.right, panelTop: b.top,
      categoriesLeft: c.left, categoriesRight: c.right,
    };
  });
  expect(geometry, "Settings navigation and active content must render").not.toBeNull();
  if (!geometry) throw new Error("Settings geometry unavailable");
  expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
  expect(geometry.rootLeft).toBeGreaterThanOrEqual(-1);
  expect(geometry.rootRight).toBeLessThanOrEqual(geometry.viewportWidth + 1);
  expect(geometry.categoriesLeft).toBeGreaterThanOrEqual(geometry.rootLeft - 1);
  expect(geometry.categoriesRight).toBeLessThanOrEqual(geometry.rootRight + 1);
  expect(geometry.panelRight).toBeLessThanOrEqual(geometry.rootRight + 1);
  if (stacked) {
    expect(geometry.panelTop).toBeGreaterThanOrEqual(geometry.navBottom - 1);
  } else {
    expect(geometry.panelLeft).toBeGreaterThanOrEqual(geometry.navRight - 1);
  }
}

test("KUI-SETTINGS: authenticated full-page categories and five viewport geometry", async (
  { page }, info: TestInfo,
) => {
  test.skip(!enabled, "Opt in with KAREN_SETTINGS_VISUAL_ACCEPTANCE=true");
  test.setTimeout(6 * 60_000);
  await page.setViewportSize(viewports[0]);
  await signIn(page);
  await openFullPageSettings(page);
  const root = page.getByTestId("karen-settings-workspace");
  await expect(root.getByRole("heading", { name: "Application Settings" })).toBeVisible();
  await expect(root.getByText("Backend-owned settings")).toBeVisible();
  await checkTheme(root);

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await checkGeometry(root, viewport.width < 1024);

    const personal = root.getByRole("tab", { name: "Personal", exact: true });
    await personal.click();
    await expect(personal).toHaveAttribute("data-state", "active");
    const privacy = root.getByRole("navigation", { name: "Personal settings sections" })
      .getByRole("button", { name: "Privacy" });
    await privacy.focus();
    await expect(privacy).toBeFocused();
    await privacy.press("Enter");
    await expect(privacy).toHaveAttribute("aria-current", "page");
    await expect(root.locator("#settings-active-panel")).toHaveAttribute("aria-label", "Privacy");

    const assistant = root.getByRole("tab", { name: "Assistant", exact: true });
    await assistant.click();
    await expect(root.getByRole("navigation", { name: "Assistant settings sections" })
      .getByRole("button", { name: "Behavior" })).toHaveAttribute("aria-current", "page");
    if (capture) {
      await info.attach(`settings-full-${viewport.width}x${viewport.height}`, {
        body: await root.screenshot({ animations: "disabled" }),
        contentType: "image/png",
      });
    }
  }
});

test("KUI-SETTINGS: narrow dashboard sheet stays stacked even on desktop", async (
  { page }, info: TestInfo,
) => {
  test.skip(!enabled, "Opt in with KAREN_SETTINGS_VISUAL_ACCEPTANCE=true");
  test.setTimeout(6 * 60_000);
  await signIn(page);
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "Settings" });
    await expect(sheet).toBeVisible();
    const root = sheet.getByTestId("karen-settings-workspace");
    await expect(root).toBeVisible();
    await checkTheme(root);
    await checkGeometry(root, true);
    const nav = root.getByRole("navigation", { name: "Assistant settings sections" });
    await expect(nav.getByRole("button", { name: "Behavior" })).toHaveAttribute(
      "aria-current", "page",
    );
    const persona = nav.getByRole("button", { name: "Persona" });
    await persona.focus();
    await expect(persona).toBeFocused();
    await persona.press("Enter");
    await expect(root.locator("#settings-active-panel")).toHaveAttribute("aria-label", "Persona");
    const runtime = root.getByRole("tab", { name: "Models & Runtime", exact: true });
    await runtime.click();
    await expect(runtime).toHaveAttribute("data-state", "active");
    await expect(root.getByRole("navigation", { name: "Models & Runtime settings sections" }))
      .toBeVisible();
    if (capture) {
      await info.attach(`settings-sheet-${viewport.width}x${viewport.height}`, {
        body: await sheet.screenshot({ animations: "disabled" }),
        contentType: "image/png",
      });
    }
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  }
});
