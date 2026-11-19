import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KUI-AUTOMATION: real authenticated browser acceptance.
 *
 * Never intercept backend APIs, inject fake list rows, or infer an empty list
 * from a failed request. This is opt-in against an approved sanitized host.
 * Do not capture private account screenshots, credentials, traces or videos.
 */
const enabled = process.env.KAREN_AUTOMATION_VISUAL_ACCEPTANCE === "true";
const sanitizedCapture = process.env.KAREN_AUTOMATION_SANITIZED_CAPTURE === "true";
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
const workspaces = [
  { label: "My tasks", title: "Task Management", api: "/api/tasks/", advanced: false },
  { label: "Jobs", title: "Jobs", api: "/api/automation/jobs/", advanced: true },
  { label: "Cron Jobs", title: "Cron Job Assignments", api: "/api/automation/cron", advanced: true },
] as const;

test.use({ trace: "off", screenshot: "off", video: "off", colorScheme: "dark" });

function approvedTarget(): URL {
  if (!approvedOrigin) throw new Error("KAREN_BASE_URL must be an approved origin.");
  const target = new URL(approvedOrigin);
  if (target.username || target.password || target.pathname !== "/" ||
      target.search || target.hash) {
    throw new Error("Credential-bearing URL or URL with path/query/fragment is forbidden.");
  }
  const local = target.protocol === "http:" &&
    ["127.0.0.1", "localhost"].includes(target.hostname) &&
    !!target.port && process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
  const release = target.protocol === "https:" && !target.port;
  if (!local && !release) {
    throw new Error("Acceptance credentials require approved HTTPS or explicitly enabled loopback.");
  }
  return target;
}

async function openWorkspace(
  page: Page, label: string, advanced: boolean,
): Promise<void> {
  // Mobile navigation may be collapsed independently of the advanced group.
  const advancedToggle = page.getByTestId("advanced-tools-toggle");
  const requiredToggle = advanced
    ? advancedToggle
    : page.getByRole("button", { name: label, exact: true });
  if (!await requiredToggle.last().isVisible().catch(() => false)) {
    const sidebarToggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(sidebarToggle).toBeVisible();
    await sidebarToggle.click();
  }
  if (advanced) {
    await expect(advancedToggle).toBeVisible();
    if (await advancedToggle.getAttribute("aria-expanded") !== "true") {
      await advancedToggle.click();
    }
  }
  const navigation = page.getByRole("button", { name: label, exact: true });
  await expect(navigation.last()).toBeVisible();
  await navigation.last().click();
}

function realListResponse(page: Page, pathname: string, origin: string) {
  return page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === origin && url.pathname === pathname &&
      response.request().method() === "GET";
  }, { timeout: 30_000 });
}

test("KUI-AUTOMATION: owner-authenticated lists, responsive surfaces and keyboard", async (
  { page }, testInfo: TestInfo,
) => {
  test.skip(!enabled, "Opt in with KAREN_AUTOMATION_VISUAL_ACCEPTANCE=true.");
  test.setTimeout(8 * 60_000);
  if (!email || !password) {
    throw new Error("Dedicated sanitized KAREN_UX_EMAIL and KAREN_UX_PASSWORD required.");
  }
  const target = approvedTarget();
  await page.setViewportSize(viewports[0]);
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });
  expect(new URL(page.url()).origin).toBe(target.origin);

  for (const workspace of workspaces) {
    const responsePromise = realListResponse(page, workspace.api, target.origin);
    await openWorkspace(page, workspace.label, workspace.advanced);
    const response = await responsePromise;
    expect(response.status(), `${workspace.label} must return real authenticated HTTP 200`).toBe(200);

    const rows: unknown = await response.json();
    expect(Array.isArray(rows), `${workspace.label} list must be an actual array`).toBe(true);
    const root = page.locator(".karen-automation-workflow");
    await expect(root.getByRole("heading", { name: workspace.title, exact: true })).toBeVisible();
    await expect(root.locator(".karen-automation-hero")).toBeVisible();
    await expect(root.getByText("Restoring your session...", { exact: true })).toHaveCount(0);
    await expect(root.getByText("Loading tasks from backend...", { exact: true })).toHaveCount(0);
    await expect(root.getByText("Loading jobs from backend...", { exact: true })).toHaveCount(0);
    await expect(root.getByText("Loading scheduled jobs from backend...", { exact: true })).toHaveCount(0);
    await expect(root.getByText(/could not be verified with the backend|Schedules unavailable/i)).toHaveCount(0);

    // The current authenticated data is authoritative: zero rows are allowed
    // only on an HTTP 200 list, not after a failed or denied read.
    if ((rows as unknown[]).length === 0) {
      const empty = workspace.label === "My tasks" ? "No live task definitions yet." :
        workspace.label === "Jobs" ? "No jobs defined yet." : "No cron jobs configured yet.";
      await expect(root.getByText(empty, { exact: true })).toBeVisible();
    }

    for (const theme of ["dark", "light"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      for (const viewport of viewports) {
        await page.setViewportSize(viewport);
        await expect(root.locator(".karen-automation-hero")).toBeVisible();
        const geometry = await root.evaluate(element => {
          const hero = element.querySelector(".karen-automation-hero");
          if (!hero) return null;
          const r = element.getBoundingClientRect();
          const h = hero.getBoundingClientRect();
          return {
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
            left: r.left,
            right: r.right,
            heroLeft: h.left,
            heroRight: h.right,
            heroWidth: h.width,
          };
        });
        expect(geometry).not.toBeNull();
        if (!geometry) throw new Error("Expected automation surface not rendered.");
        expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
        expect(geometry.heroWidth).toBeGreaterThan(0);
        expect(geometry.heroLeft).toBeGreaterThanOrEqual(-1);
        expect(geometry.heroRight).toBeLessThanOrEqual(geometry.viewportWidth + 1);
        expect(geometry.left).toBeGreaterThanOrEqual(-1);
        expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 1);

        if (sanitizedCapture) {
          await testInfo.attach(
            `automation-${workspace.label.replaceAll(" ", "-")}-${theme}-${viewport.width}x${viewport.height}`,
            { body: await root.screenshot({ animations: "disabled" }), contentType: "image/png" },
          );
        }
      }
    }

    // Real keyboard focus is required on a live control, not a fabricated toggle.
    const focused = root.locator("button:not([disabled])").first();
    await expect(focused).toBeVisible();
    await focused.focus();
    await expect(focused).toBeFocused();
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize(viewports[0]);
  }
});
