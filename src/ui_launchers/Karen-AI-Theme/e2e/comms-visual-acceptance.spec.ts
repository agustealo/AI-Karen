import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KUI-COMMS: authenticated, real-service visual and interaction acceptance.
 *
 * This opt-in suite deliberately does not intercept APIs, mock audit records,
 * invent metrics, or modify the canonical Communications Center.
 *
 * Required:
 *   KAREN_COMMS_VISUAL_ACCEPTANCE=true
 *   KAREN_BASE_URL=http://127.0.0.1:8010  (local) or approved HTTPS origin
 *   KAREN_UX_EMAIL / KAREN_UX_PASSWORD for a sanitized test principal
 *   KAREN_LOCAL_CHAT_ACCEPTANCE=1 for local loopback credential authorization
 *
 * Optional sanitized evidence only:
 *   KAREN_COMMS_SANITIZED_CAPTURE=true
 *
 * The capture opt-in must only be used with a dedicated, sanitized account.
 * Screenshots do not prove pixel parity without independent reference review.
 */

const enabled = process.env.KAREN_COMMS_VISUAL_ACCEPTANCE === "true";
const sanitizedCapture = process.env.KAREN_COMMS_SANITIZED_CAPTURE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const approvedOrigin = process.env.KAREN_BASE_URL;
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

test.use({
  trace: "off",
  screenshot: "off",
  video: "off",
  colorScheme: "dark",
});

function validateTarget(): URL {
  if (!approvedOrigin) {
    throw new Error("KAREN_BASE_URL must identify an approved browser test origin");
  }
  const target = new URL(approvedOrigin);
  if (target.username || target.password || target.pathname !== "/" ||
      target.search || target.hash) {
    throw new Error("Approved URL must be an unadorned origin");
  }
  const isLocal = target.protocol === "http:" &&
    (target.hostname === "localhost" || target.hostname === "127.0.0.1") &&
    target.port !== "" && process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
  const isHttps = target.protocol === "https:" && target.port === "";
  if (!isLocal && !isHttps) {
    throw new Error("Refusing credentials on unapproved HTTP or non-loopback origin");
  }
  return target;
}

async function openCommunications(page: Page): Promise<void> {
  const navName = "Activity & notifications";
  let navigation = page.getByRole("button", { name: navName, exact: true });
  if (!(await navigation.first().isVisible().catch(() => false))) {
    const trigger = page.locator('[data-sidebar="trigger"]').first();
    await expect(trigger).toBeVisible();
    await trigger.click();
    navigation = page.getByRole("button", { name: navName, exact: true });
  }
  const visibleNav = navigation.last();
  await expect(visibleNav).toBeVisible();
  await visibleNav.click();
  await expect(page.getByTestId("comms-center")).toBeVisible({ timeout: 30_000 });
}

test("KUI-COMMS: live identity-scoped evidence and five responsive viewports", async (
  { page }, testInfo: TestInfo,
) => {
  test.skip(!enabled, "Opt in using KAREN_COMMS_VISUAL_ACCEPTANCE=true");
  test.setTimeout(5 * 60_000);
  if (!email || !password) {
    throw new Error("Dedicated sanitized KAREN_UX_EMAIL and KAREN_UX_PASSWORD are required");
  }
  const target = validateTarget();
  await page.setViewportSize(viewports[0]);

  // Reuse the repository-owned, origin-locked real login flow.
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });
  expect(new URL(page.url()).origin).toBe(target.origin);

  const endpoint = "/api/communications-center/observability";
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === endpoint &&
      response.request().method() === "GET";
  }, { timeout: 30_000 });

  await openCommunications(page);
  const response = await responsePromise;
  expect(response.status(), "Sanitized principal must be authorized by the real API").toBe(200);
  const rawSnapshot: unknown = await response.json();
  expect(rawSnapshot).toBeTruthy();
  if (!rawSnapshot || typeof rawSnapshot !== "object" ||
      !("generated_at" in rawSnapshot) ||
      !("audit" in rawSnapshot) ||
      !("training" in rawSnapshot) ||
      !("memory" in rawSnapshot) ||
      !("alerts" in rawSnapshot)) {
    throw new Error("Live Communications response violates its expected contract");
  }

  const root = page.getByTestId("comms-center");
  await expect(root.getByRole("heading", { name: "Activity & Notifications" })).toBeVisible();
  await expect(root.locator("header [role=\"status\"]")).toContainText("Live snapshot");
  await expect(root.getByTestId("comms-metric-audit")).not.toHaveText("—");
  await expect(root.getByTestId("comms-metric-alerts")).not.toHaveText("—");

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(root).toBeVisible();

    // Test the actual shared Kari OS opt-in and its computed graphite token.
    const appearance = await root.evaluate((element) => ({
      canvas: getComputedStyle(element).getPropertyValue("--kari-canvas").trim(),
      panel: getComputedStyle(element).getPropertyValue("--kari-panel").trim(),
      font: getComputedStyle(element).fontFamily,
      headingFont: getComputedStyle(element.querySelector(".kari-display")!).fontFamily,
    }));
    expect(appearance.canvas).toBe("#070708");
    expect(appearance.panel).toBe("#0d0e0f");
    expect(appearance.font).toMatch(/Inter/i);
    expect(appearance.headingFont).toMatch(/Manrope/i);

    // Horizontal scrolling is supported inside the accessible tab strip, not
    // across the document or out of the visible content region.
    const geometry = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="comms-center"]');
      const header = panel?.querySelector("header");
      if (!panel || !header) return null;
      const width = document.documentElement.clientWidth;
      const rect = panel.getBoundingClientRect();
      const hero = header.getBoundingClientRect();
      return {
        width,
        documentWidth: document.documentElement.scrollWidth,
        panelLeft: rect.left,
        panelRight: rect.right,
        heroLeft: hero.left,
        heroRight: hero.right,
      };
    });
    expect(geometry, "Communications layout must render").not.toBeNull();
    if (!geometry) throw new Error("Missing Communications geometry");
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.width + 1);
    expect(geometry.heroLeft).toBeGreaterThanOrEqual(-1);
    expect(geometry.heroRight).toBeLessThanOrEqual(geometry.width + 1);
    expect(geometry.panelLeft).toBeGreaterThanOrEqual(-1);
    expect(geometry.panelRight).toBeLessThanOrEqual(geometry.width + 1);

    const tabs = root.getByRole("tablist");
    await expect(tabs).toBeVisible();
    await expect(tabs.getByRole("tab")).toHaveCount(5);
    const auditTab = tabs.getByRole("tab", { name: "Audit timeline" });
    await auditTab.focus();
    await expect(auditTab).toBeFocused();
    await auditTab.press("Enter");
    await expect(auditTab).toHaveAttribute("data-state", "active");
    const overviewTab = tabs.getByRole("tab", { name: "Overview" });
    await overviewTab.click();
    await expect(overviewTab).toHaveAttribute("data-state", "active");

    const refresh = root.getByRole("button", { name: "Refresh" });
    await expect(refresh).toBeEnabled();
    await refresh.focus();
    await expect(refresh).toBeFocused();

    if (sanitizedCapture) {
      await testInfo.attach("comms-sanitized-" + viewport.width + "x" + viewport.height, {
        body: await root.screenshot({ animations: "disabled" }),
        contentType: "image/png",
      });
    }
  }

  // Verify that Refresh is a real data action, not a simulated UI toggle.
  const refreshRequest = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === endpoint && response.request().method() === "GET";
  }, { timeout: 30_000 });
  await root.getByRole("button", { name: "Refresh" }).click();
  const refreshed = await refreshRequest;
  expect(refreshed.status()).toBe(200);
  await expect(root.getByRole("status")).toContainText("Live snapshot");
});
