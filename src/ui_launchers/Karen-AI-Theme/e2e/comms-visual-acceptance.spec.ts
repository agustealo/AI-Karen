import { expect, test, type Page, type TestInfo, type Request as BrowserRequest } from "@playwright/test";
import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import { openAutomationWorkspace } from "./fixtures/automation-workspace-navigation";
import { INBOX_PATH, readPage, readReceipt, type InboxEntry, type InboxFilter, type InboxOperation } from "../src/components/comms/communications-inbox-contract";

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
  const navName = "Activity";
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
  await expect(root.getByRole("heading", { name: "Your communications & activity" })).toBeVisible();
  await expect(root.locator("header [role=\"status\"]")).toContainText("Snapshot received");
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
    await expect(tabs.getByRole("tab")).toHaveCount(7);
    await expect(tabs.getByRole("tab", { name: "Inbox" })).toBeVisible();
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
  await expect(root.locator("header [role=\"status\"]")).toContainText("Snapshot received");

  // Read-only proof of the real shared approval inbox. No decision is made.
  await root.getByRole("button", { name: "Review decisions" }).click();
  const decisions = root.getByTestId("comms-decisions-inbox");
  await expect(decisions).toBeVisible();
  const approvalRead = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin && url.pathname === "/api/approvals/" && response.request().method() === "GET";
  }, { timeout: 30_000 });
  await decisions.getByRole("button", { name: "Refresh decisions" }).click();
  const approvalResponse = await approvalRead;
  expect(approvalResponse.status()).toBe(200);
  const approvalRecords: unknown = await approvalResponse.json();
  if (!Array.isArray(approvalRecords)) throw new Error("Canonical approval list is not an array");
  await expect(decisions.getByTestId("approval-review-record")).toHaveCount(approvalRecords.length);
  await expect(decisions.getByText("Could not load approval requests.")).toHaveCount(0);
  await root.getByRole("tab", { name: "Overview" }).click();

  // Navigation only: the Communications Center must reuse the authorized
  // Agent Runtime approval workspace, without submitting any decision.
  await root.getByRole("button", { name: "Open approval workspace" }).click();
  const agentWorkspace = page.getByTestId("agent-runtime-page");
  await expect(agentWorkspace).toBeVisible();
  await expect(agentWorkspace.getByTestId("agent-runtime-approvals")).toBeVisible();
  await expect(root).not.toBeVisible();
  await openCommunications(page);
  await expect(root.getByRole("heading", { name: "Your communications & activity" })).toBeVisible();
});


/**
 * An independently opted-in real Medusa proof.
 *
 * Use an approved, sanitized account which already has at least one genuine
 * Medusa execution with a recorded start time. Do not seed or mock it here:
 * only the runtime may author execution records. This suite deliberately
 * fails if no qualifying real record exists.
 */
test("KUI-COMMS: authenticated Medusa run receipts render and refresh", async ({ page }) => {
  test.skip(
    !enabled || process.env.KAREN_COMMS_AGENT_FEED_ACCEPTANCE !== "true",
    "Requires KAREN_COMMS_VISUAL_ACCEPTANCE=true and KAREN_COMMS_AGENT_FEED_ACCEPTANCE=true",
  );
  test.setTimeout(2 * 60_000);
  if (!email || !password) {
    throw new Error("Dedicated sanitized KAREN_UX_EMAIL and KAREN_UX_PASSWORD are required");
  }

  const origin = validateTarget().origin;
  const endpoint = "/api/agent-runtime/my-runs";
  const isOwnedRunResponse = (response: import("@playwright/test").Response): boolean => {
    const url = new URL(response.url());
    return url.origin === origin &&
      url.pathname === endpoint &&
      response.request().method() === "GET";
  };

  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });
  expect(new URL(page.url()).origin).toBe(origin);

  const firstRequest = page.waitForResponse(isOwnedRunResponse, { timeout: 30_000 });
  await openCommunications(page);
  const first = await firstRequest;
  expect(first.status(), "Canonical owner-scoped Medusa endpoint must authorize this principal").toBe(200);

  const body: unknown = await first.json();
  if (!body || typeof body !== "object" || !("runs" in body) ||
      !Array.isArray(body.runs) || !("total" in body) ||
      typeof body.total !== "number" || !("generated_at" in body) ||
      typeof body.generated_at !== "string") {
    throw new Error("Real Medusa endpoint returned an invalid execution-list contract");
  }
  const runs: unknown[] = body.runs;
  expect(runs.length, "Sanitized principal needs an existing real Medusa run for this acceptance").toBeGreaterThan(0);
  expect(body.total).toBeGreaterThanOrEqual(runs.length);

  const owned = runs.map((item) => {
    if (!item || typeof item !== "object" ||
        !("run_id" in item) || typeof item.run_id !== "string" ||
        !("tenant_id" in item) || typeof item.tenant_id !== "string" ||
        !("user_id" in item) || typeof item.user_id !== "string" ||
        !("status" in item) || typeof item.status !== "string" ||
        !("started_at" in item) || typeof item.started_at !== "string") {
      throw new Error("Real Medusa response lacks required run ownership or receipt fields");
    }
    return {
      id: item.run_id,
      tenant: item.tenant_id,
      user: item.user_id,
      status: item.status,
      startedAt: item.started_at,
    };
  });
  const principal = owned[0];
  expect(principal.tenant.length).toBeGreaterThan(0);
  expect(principal.user.length).toBeGreaterThan(0);
  for (const run of owned) {
    expect(run.tenant, "Mixed-tenant Medusa response must not be accepted").toBe(principal.tenant);
    expect(run.user, "Mixed-owner Medusa response must not be accepted").toBe(principal.user);
    expect(run.id.length).toBeGreaterThan(0);
    expect(run.id.length).toBeLessThanOrEqual(128);
    expect(Number.isNaN(Date.parse(run.startedAt))).toBe(false);
  }

  const card = page.getByTestId("comms-owned-runs");
  await expect(card.getByText("Recent agent executions")).toBeVisible();
  await expect(card.getByTestId("comms-owned-run-count")).toContainText(
    String(owned.length) + " recorded",
  );
  const visibleRun = owned[0];
  const receipt = card.getByRole("listitem").filter({
    hasText: "Execution " + visibleRun.id.slice(0, 8),
  });
  await expect(receipt).toBeVisible();
  await expect(receipt).toContainText(visibleRun.status);
  const expectedStartTime = await page.evaluate((startedAt) => {
    const started = new Date(startedAt);
    const month = started.toLocaleString("en-US", { month: "short" });
    const day = started.getDate();
    const hour = String(started.getHours()).padStart(2, "0");
    const minute = String(started.getMinutes()).padStart(2, "0");
    return `Started ${month} ${day}, ${hour}:${minute}`;
  }, visibleRun.startedAt);
  await expect(receipt).toContainText(expectedStartTime);
  await expect(receipt).not.toContainText("Time unavailable");
  await expect(card).toContainText("does not imply an independently verified result");

  const refreshedRequest = page.waitForResponse(isOwnedRunResponse, { timeout: 30_000 });
  await page.getByTestId("comms-center").getByRole("button", { name: "Refresh" }).click();
  const refreshed = await refreshedRequest;
  expect(refreshed.status(), "Refresh must make another authenticated Medusa request").toBe(200);
  await expect(card.getByTestId("comms-owned-run-count")).not.toContainText("Unverified");
});


/**
 * Explicitly authorized destructive lifecycle acceptance on disposable,
 * already runtime-produced notification fixtures only. No synthetic records,
 * no route interception, no database seeding, no execution retry.
 */
test("KCOMM-02E: real signed-session recovery, lifecycle persistence and account isolation", async ({ page }) => {
  test.skip(process.env.KAREN_COMMS_INBOX_ACCEPTANCE !== "true", "Opt in to dedicated disposable inbox lifecycle acceptance");
  test.setTimeout(5 * 60_000);
  const accountB = process.env.KAREN_UX_ACCOUNT_B_EMAIL;
  const passwordB = process.env.KAREN_UX_ACCOUNT_B_PASSWORD;
  const runA = process.env.KAREN_UX_ACCOUNT_A_PENDING_INBOX_EXECUTION_ID;
  const runB = process.env.KAREN_UX_ACCOUNT_B_INBOX_EXECUTION_ID;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  if (!email || !password || !accountB || !passwordB || email.toLowerCase() === accountB.toLowerCase()
      || !runA || !runB || !uuid.test(runA) || !uuid.test(runB) || runA === runB || runA.slice(0,8) === runB.slice(0,8)) {
    throw new Error("Two distinct disposable accounts and two genuine distinct runtime execution IDs are required");
  }
  const origin = validateTarget().origin;
  const options = { allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1" };
  const inbox = page.getByTestId("personal-communications-inbox");
  const root = page.getByTestId("comms-center");
  const responseFor = (method: string, path: string, filter?: InboxFilter) => page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === origin && url.pathname === path && response.request().method() === method
      && (filter === undefined || (url.searchParams.get("inbox_filter") === filter && !url.searchParams.has("cursor_id")));
  }, { timeout: 30_000 });
  async function readAfter(action: () => Promise<unknown>, filter: InboxFilter) {
    const pending = responseFor("GET", INBOX_PATH, filter);
    await action();
    const response = await pending;
    expect(response.status()).toBe(200);
    const projection = readPage(await response.json(), filter, null);
    await expect(inbox.getByTestId("personal-inbox-unread")).toHaveText(projection.active_unread_count + " unread active");
    return projection;
  }
  function locateEntry(entry: InboxEntry) {
    return inbox.getByRole("listitem").filter({ hasText: "Execution " + entry.execution_id.slice(0, 8) });
  }
  async function openInbox() {
    await openCommunications(page);
    return readAfter(() => root.getByRole("tab", { name: "Inbox", exact: true }).click(), "active");
  }
  async function mutate(entry: InboxEntry, operation: InboxOperation, label: string) {
    const row = locateEntry(entry);
    await expect(row).toHaveCount(1);
    const receiptPending = responseFor("PATCH", INBOX_PATH + "/" + entry.entry_id);
    const reread = responseFor("GET", INBOX_PATH, "active");
    await row.getByRole("button", { name: label, exact: true }).click();
    const response = await receiptPending;
    expect(response.status()).toBe(200);
    const body = response.request().postDataJSON();
    expect(body).toEqual({ operation, expected_revision: entry.revision });
    const receipt = readReceipt(await response.json(), entry, operation);
    expect(receipt.changed).toBe(true);
    const refreshed = await reread;
    expect(refreshed.status()).toBe(200);
    const projection = readPage(await refreshed.json(), "active", null);
    await expect(inbox.getByTestId("personal-inbox-unread")).toHaveText(projection.active_unread_count + " unread active");
    if (operation === "archive") {
      expect(projection.entries.some(e => e.entry_id === entry.entry_id)).toBe(false);
      await expect(row).toHaveCount(0);
    } else {
      const durable = projection.entries.find(e => e.entry_id === entry.entry_id);
      expect(durable).toEqual(receipt.entry);
      await expect(row).toContainText(operation === "read" ? "Read" : "Acknowledged");
    }
    return receipt.entry;
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInApprovedKaren(page, email, password, options);
  const before = await openInbox();
  expect(before.entries.some(e => e.execution_id === runA || e.execution_id === runB)).toBe(false);
  const recovery = responseFor("POST", INBOX_PATH + "/reconcile");
  const afterRecovery = readAfter(() => inbox.getByRole("button", { name: "Recover missed notifications" }).click(), "active");
  const recoveryResponse = await recovery;
  expect(recoveryResponse.status()).toBe(200);
  const count: unknown = (await recoveryResponse.json()).admitted_count;
  expect(typeof count === "number" && Number.isSafeInteger(count) && count >= 1 && count <= 50).toBe(true);
  const recovered = await afterRecovery;
  const admitted = recovered.entries.find(e => e.execution_id === runA);
  if (!admitted || admitted.read_at || admitted.acknowledged_at || admitted.archived_at) {
    throw new Error("Expected newly recovered unread runtime fixture on first page");
  }
  expect(recovered.entries.some(e => e.execution_id === runB)).toBe(false);
  const read = await mutate(admitted, "read", "Mark read");
  const acknowledged = await mutate(read, "acknowledge", "Acknowledge");
  const archived = await mutate(acknowledged, "archive", "Archive");
  const archivedPage = await readAfter(() => inbox.getByRole("button", { name: "Archived", exact: true }).click(), "archived");
  expect(archivedPage.entries.find(e => e.entry_id === archived.entry_id)).toEqual(archived);
  await expect(locateEntry(archived)).toContainText("Archived");
  await page.reload();
  await openInbox();
  const afterReload = await readAfter(() => inbox.getByRole("button", { name: "Archived", exact: true }).click(), "archived");
  expect(afterReload.entries.find(e => e.entry_id === archived.entry_id)).toEqual(archived);

  // Prove logout at the backend, not merely a client redirect.
  await openAutomationWorkspace(page, "My Account", false);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:[?#]|$)/, { timeout: 30_000 });
  const signedOutStatus = await page.evaluate(async path => (await fetch(path, { credentials: "same-origin", cache: "no-store" })).status, INBOX_PATH);
  expect([401, 403]).toContain(signedOutStatus);
  await signInApprovedKaren(page, accountB, passwordB, options);
  const other = await openInbox();
  expect(other.entries.some(e => e.execution_id === runB)).toBe(true);
  expect(other.entries.some(e => e.entry_id === archived.entry_id || e.execution_id === runA)).toBe(false);
  await expect(inbox.getByText("Execution " + runA.slice(0,8), { exact: false })).toHaveCount(0);
  const otherArchived = await readAfter(() => inbox.getByRole("button", { name: "Archived", exact: true }).click(), "archived");
  expect(otherArchived.entries.some(e => e.entry_id === archived.entry_id || e.execution_id === runA)).toBe(false);
});


/** Genuine production-image HTTP/browser delivery; no interception or synthetic events. */
test("KCOMM-03G: committed change delivery, cancellation and live session revocation", async ({ page, request }) => {
  test.skip(process.env.KAREN_COMMS_INVALIDATION_ACCEPTANCE !== "true", "Explicit disposable invalidation opt-in required");
  test.setTimeout(5 * 60_000);
  const target = validateTarget();
  const accountB = process.env.KAREN_UX_ACCOUNT_B_EMAIL;
  const passwordB = process.env.KAREN_UX_ACCOUNT_B_PASSWORD;
  const runB = process.env.KAREN_UX_ACCOUNT_B_INBOX_EXECUTION_ID;
  const tenant = process.env.KAREN_COMMS_WITNESS_TENANT;
  const ownerA = process.env.KAREN_COMMS_WITNESS_OWNER_A;
  const ownerB = process.env.KAREN_COMMS_WITNESS_OWNER_B;
  const apiContainer = process.env.KAREN_COMMS_WITNESS_API_CONTAINER;
  const network = process.env.KAREN_COMMS_WITNESS_NETWORK;
  const apiOrigin = process.env.KAREN_COMMS_WITNESS_API_URL;
  const python = process.env.KAREN_COMMS_WITNESS_PYTHON;
  if (target.protocol !== "http:" || target.hostname !== "127.0.0.1" ||
      process.env.KAREN_SMOKE_COMMS_BROWSER_PROOF !== "true" ||
      !email || !password || !accountB || !passwordB || !runB || !tenant ||
      !ownerA || !ownerB || ownerA === ownerB || !apiContainer || !network || !apiOrigin || !python) {
    throw new Error("Isolated signed-session invalidation fixture required");
  }
  if (![tenant, ownerA, ownerB, runB].every(v => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v))) {
    throw new Error("Invalid disposable witness identities");
  }
  const origin = target.origin;
  const waitPath = INBOX_PATH + "/wait";
  const inbox = page.getByTestId("personal-communications-inbox");
  const root = page.getByTestId("comms-center");
  const execute = promisify(execFile);
  const witnessScript = resolve(process.cwd(), "../../../scripts/ci/communications_browser_smoke.py");
  async function witness(owners: string[], count: 0 | 1) {
    const args = [witnessScript, "--api-container", apiContainer!, "--network", network!,
      "--api-url", apiOrigin!, "--tenant-id", tenant!, "--expected-count", String(count)];
    for (const owner of owners) args.push("--observe-owner", owner);
    const result = await execute(python!, args, { timeout: 20_000, maxBuffer: 64 * 1024 });
    if (result.stdout.trim() !== "DISPOSABLE COMMUNICATIONS BROKER WITNESS PASSED") {
      throw new Error("Broker witness missing");
    }
  }
  async function login(actorEmail: string, actorPassword: string, owner: string) {
    const response = await request.post(origin + "/api/auth/login", {
      data: { email: actorEmail, password: actorPassword }, maxRedirects: 0,
    });
    if (response.status() !== 200) throw new Error("Fixture login failed");
    const raw = await response.json();
    if (raw?.user?.user_id !== owner || raw?.user?.tenant_id !== tenant ||
        typeof raw.access_token !== "string" || !raw.access_token ||
        typeof raw.refresh_token !== "string" || !raw.refresh_token) {
      throw new Error("Fixture login identity mismatch");
    }
    return { Authorization: "Bearer " + raw.access_token };
  }
  const waitRequest = (req: BrowserRequest) => {
    const url = new URL(req.url());
    return url.origin === origin && url.pathname === waitPath && req.method() === "GET";
  };
  const inboxRequest = (req: BrowserRequest) => {
    const url = new URL(req.url());
    return url.origin === origin && url.pathname === INBOX_PATH && req.method() === "GET"
      && url.searchParams.get("inbox_filter") === "active" && !url.searchParams.has("cursor_id");
  };
  const aHeaders = await login(email, password, ownerA);
  const bHeaders = await login(accountB, passwordB, ownerB);
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInApprovedKaren(page, accountB, passwordB, { allowLocalLoopback: true });
  await openCommunications(page);
  const initialRead = page.waitForResponse(res => inboxRequest(res.request()), { timeout: 30_000 });
  const browserWait = page.waitForRequest(waitRequest, { timeout: 30_000 });
  await root.getByRole("tab", { name: "Inbox", exact: true }).click();
  const initial = await initialRead;
  expect(initial.status()).toBe(200);
  const raw = await initial.json();
  // Deliberately read the backend capability, not a browser configuration flag.
  expect(raw?.capabilities?.invalidation_wait_enabled).toBe(true);
  const projection = readPage(raw, "active", null);
  const entry = projection.entries.find(e => e.execution_id === runB);
  if (!entry || entry.read_at || entry.acknowledged_at || entry.archived_at) {
    throw new Error("Fresh unread owner B fixture required");
  }
  await expect(inbox.getByTestId("personal-inbox-unread")).toHaveText(projection.active_unread_count + " unread active");
  const ownerRequest = await browserWait;
  const sequence: string[] = [];
  const recordRequest = (req: BrowserRequest) => { if (inboxRequest(req)) sequence.push("read"); };
  const recordResponse = (res: import("@playwright/test").Response) => {
    if (res.request() === ownerRequest) sequence.push("hint");
  };
  page.on("request", recordRequest);
  page.on("response", recordResponse);
  try {
    const hintPending = page.waitForResponse(res => res.request() === ownerRequest, { timeout: 20_000 });
    const readPending = page.waitForResponse(res => inboxRequest(res.request()), { timeout: 20_000 });
    const foreignPending = request.get(origin + waitPath, { headers: aHeaders, timeout: 25_000, maxRedirects: 0 });
    await witness([ownerA, ownerB], 1);
    const patch = await request.patch(origin + INBOX_PATH + "/" + entry.entry_id, {
      headers: bHeaders, data: { operation: "read", expected_revision: entry.revision }, maxRedirects: 0,
    });
    expect(patch.status()).toBe(200);
    const read = readReceipt(await patch.json(), entry, "read");
    expect(read.changed).toBe(true);
    const hint = await hintPending;
    expect(hint.status()).toBe(200);
    expect(await hint.json()).toEqual({ changed: true });
    expect(hint.headers()["cache-control"]).toBe("no-store");
    const reread = await readPending;
    expect(reread.status()).toBe(200);
    expect(sequence[0]).toBe("hint");
    expect(sequence[1]).toBe("read");
    expect(readPage(await reread.json(), "active", null).entries.find(e => e.entry_id === entry.entry_id)).toEqual(read.entry);
    await expect(inbox.getByRole("listitem").filter({ hasText: "Execution " + runB.slice(0, 8) })).toContainText("Read");
    const foreign = await foreignPending;
    expect(foreign.status()).toBe(200);
    expect(await foreign.json()).toEqual({ changed: false });
    expect(foreign.headers()["cache-control"]).toBe("no-store");

    // Begin a newly observed wait after the foreign idle window; leave the
    // workspace while it is subscribed and require browser failure plus zero
    // broker subscriptions, not merely a successful navigation.
    const cancellable = await page.waitForRequest(waitRequest, { timeout: 30_000 });
    const failed = page.waitForEvent("requestfailed", { predicate: req => req === cancellable, timeout: 12_000 });
    await witness([ownerB], 1);
    await openAutomationWorkspace(page, "My Account", false);
    await failed;
    await witness([ownerB], 0);

    const reopened = page.waitForRequest(waitRequest, { timeout: 30_000 });
    await openCommunications(page);
    await root.getByRole("tab", { name: "Inbox", exact: true }).click();
    const revokedRequest = await reopened;
    const denied = page.waitForResponse(res => res.request() === revokedRequest, { timeout: 25_000 });
    await witness([ownerB], 1);
    // Revoke the browser's exact active credentials via the real logout API,
    // without resetting its UI state. Never expose tokens to the test runner.
    const logoutStatus = await page.evaluate(async () => {
      const access = localStorage.getItem("access_token");
      const refresh = localStorage.getItem("refresh_token");
      if (!access || !refresh) throw new Error("Browser session credentials unavailable");
      const result = await fetch("/api/auth/logout", {
        method: "POST", redirect: "error", cache: "no-store", credentials: "same-origin",
        headers: { Authorization: "Bearer " + access, "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      return result.status;
    });
    expect(logoutStatus).toBe(200);
    await witness([ownerB], 1);
    // The independent signed owner session is still authorized to commit.
    // Its real post-commit signal must not be returned to the revoked waiter.
    const ack = await request.patch(origin + INBOX_PATH + "/" + entry.entry_id, {
      headers: bHeaders, data: { operation: "acknowledge", expected_revision: read.entry.revision }, maxRedirects: 0,
    });
    expect(ack.status()).toBe(200);
    expect(readReceipt(await ack.json(), read.entry, "acknowledge").changed).toBe(true);
    const rejection = await denied;
    expect([401, 403]).toContain(rejection.status());
    expect(rejection.headers()["cache-control"]).toBe("no-store");
    const rejectionBody = await rejection.json();
    expect(rejectionBody).not.toHaveProperty("changed");
    await witness([ownerB], 0);
    const staleStatus = await page.evaluate(async path => {
      const access = localStorage.getItem("access_token");
      if (!access) throw new Error("Revoked bearer unavailable for backend verification");
      return (await fetch(path, {
        headers: { Authorization: "Bearer " + access }, cache: "no-store", redirect: "error", credentials: "same-origin",
      })).status;
    }, INBOX_PATH);
    expect([401, 403]).toContain(staleStatus);
  } finally {
    page.off("request", recordRequest);
    page.off("response", recordResponse);
  }
});
