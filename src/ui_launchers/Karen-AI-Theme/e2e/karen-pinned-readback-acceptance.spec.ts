import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KUI-002D3F: real authenticated browser acceptance for the EXISTING read-only
 * pinned reference dock. Never intercept requests, seed browser state, inject
 * a principal, synthesize cards, or enable mutation feature flags.
 *
 * Opt-in on a sanitized, approved deployment with a genuinely saved and
 * freshly admissible pin:
 *   KAREN_PIN_READBACK_ACCEPTANCE=1
 *   KAREN_BASE_URL=https://<approved-host>/
 *   KAREN_UX_EMAIL and KAREN_UX_PASSWORD
 *   KAREN_PIN_READBACK_PIN_ID=<owned persisted UUID>
 * Optional isolation proof requires BOTH:
 *   KAREN_PIN_FOREIGN_EMAIL and KAREN_PIN_FOREIGN_PASSWORD
 *
 * Pin/unpin/reorder controls and reconstructed presentations are NOT asserted:
 * the consumer dock intentionally exposes neither today.
 */
const enabled = process.env.KAREN_PIN_READBACK_ACCEPTANCE === "1";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const expectedPinId = process.env.KAREN_PIN_READBACK_PIN_ID;
const foreignEmail = process.env.KAREN_PIN_FOREIGN_EMAIL;
const foreignPassword = process.env.KAREN_PIN_FOREIGN_PASSWORD;

if (enabled && (
  !email || !password || !expectedPinId ||
  !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(expectedPinId)
)) {
  throw new Error("Pinned readback acceptance needs real credentials and an owned, persisted pin UUID");
}
if (enabled && Boolean(foreignEmail) !== Boolean(foreignPassword)) {
  throw new Error("Foreign pin isolation needs both credentials; no synthetic session fallback");
}

// Authentication actions, user records and saved reference identifiers must
// not enter trace files, videos, screenshots or HTML/JSON reporters.
test.use({ viewport: { width: 1720, height: 980 }, trace: "off", screenshot: "off", video: "off" });
test.describe("real authenticated saved-pin reference readback", () => {
  test.skip(!enabled, "Opt in with a real approved deployment and saved pin");

  test("shows only backend-authorized pin references and revalidates on reload", async ({ page }) => {
    await signInApprovedKaren(page, email!, password!);
    await page.goto("/dashboard");
    const shell = page.getByTestId("karen-copilot-consumer-chat");
    await expect(shell).toBeVisible({ timeout: 30_000 });
    const dock = page.getByTestId("karen-copilot-pinned-dock");
    await expect(dock).toBeVisible();

    const readback = await page.evaluate(async () => {
      const token = window.localStorage.getItem("access_token");
      const response = await window.fetch("/api/chat/ag-ui/pins", {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      return {
        status: response.status,
        cache: response.headers.get("cache-control"),
        body: response.ok ? await response.json() as unknown : null,
      };
    });
    expect(readback.status, "The existing backend must authorize fresh pin readback").toBe(200);
    expect(readback.cache).toContain("no-store");
    const body = readback.body as {
      schema_version?: number;
      read_only?: boolean;
      pins?: Array<{
        pin_id: string;
        position: number;
        revision: number;
        source: { component_type: string; presentation_id: string };
      }>;
    };
    expect(body.schema_version).toBe(1);
    expect(body.read_only).toBe(true);
    expect(Array.isArray(body.pins)).toBe(true);
    const pin = body.pins?.find(item => item.pin_id === expectedPinId);
    expect(pin, "Seeded pin must survive current source authorization").toBeDefined();
    expect(body.pins?.filter(item => item.pin_id === expectedPinId)).toHaveLength(1);
    if (!pin) return;

    const authorized = dock.getByTestId("karen-pins-authorized");
    await expect(authorized).toBeVisible();
    const savedLabel = `Saved reference ${pin.position + 1} · Revision ${pin.revision}`;
    const savedRow = authorized.locator("article").filter({ hasText: savedLabel });
    await expect(savedRow).toHaveCount(1);
    await expect(savedRow.getByText(
      pin.source.component_type.split(".").join(" · "), { exact: true },
    )).toBeVisible();
    await expect(savedRow.getByText(savedLabel, { exact: true })).toBeVisible();
    await expect(dock.getByTestId("karen-pinning-not-available")).toHaveCount(0);
    await expect(dock.getByTestId("karen-pins-empty")).toHaveCount(0);
    // References are NOT renderable card data, even for a verified owner.
    await expect(dock.getByTestId("karen-weather-presentation")).toHaveCount(0);
    await expect(dock.getByTestId("karen-planner-task-list")).toHaveCount(0);

    await page.reload();
    await expect(shell).toBeVisible({ timeout: 30_000 });
    const restored = dock.getByTestId("karen-pins-authorized");
    await expect(restored).toBeVisible();
    const restoredRow = restored.locator("article").filter({ hasText: savedLabel });
    await expect(restoredRow).toHaveCount(1);
    await expect(restoredRow.getByText(savedLabel, { exact: true })).toBeVisible();
    await expect(dock.getByTestId("karen-pinning-not-available")).toHaveCount(0);
  });

  test("foreign authenticated account never displays the owned saved pin", async ({ page }) => {
    test.skip(!foreignEmail || !foreignPassword,
      "Provide a separately authenticated real account for cross-user readback proof");
    await signInApprovedKaren(page, foreignEmail!, foreignPassword!);
    await page.goto("/dashboard");
    const dock = page.getByTestId("karen-copilot-pinned-dock");
    await expect(dock).toBeVisible();
    await expect(dock.getByTestId("karen-pins-loading")).toHaveCount(0);
    const contents = await page.evaluate(async () => {
      const token = window.localStorage.getItem("access_token");
      const response = await window.fetch("/api/chat/ag-ui/pins", {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      return {
        status: response.status,
        body: response.ok ? await response.json() as unknown : null,
      };
    });
    if (contents.status === 200) {
      const snapshot = contents.body as {
        schema_version?: number;
        read_only?: boolean;
        pins?: Array<{
          pin_id: string;
          position: number;
          revision: number;
          source: { component_type: string };
        }>;
      };
      expect(snapshot.schema_version).toBe(1);
      expect(snapshot.read_only).toBe(true);
      expect(Array.isArray(snapshot.pins)).toBe(true);
      const pins = snapshot.pins!;
      expect(pins).not.toContainEqual(
        expect.objectContaining({ pin_id: expectedPinId }),
      );
      expect(new Set(pins.map(pin => pin.pin_id)).size).toBe(pins.length);
      expect(new Set(pins.map(pin => pin.position)).size).toBe(pins.length);

      if (pins.length === 0) {
        await expect(dock.getByTestId("karen-pins-empty")).toBeVisible();
        await expect(dock.getByTestId("karen-pins-authorized")).toHaveCount(0);
      } else {
        const authorized = dock.getByTestId("karen-pins-authorized");
        await expect(authorized).toBeVisible();
        const rows = authorized.locator("article");
        await expect(rows).toHaveCount(pins.length);
        const ordered = [...pins].sort((left, right) => left.position - right.position);
        for (const [index, pin] of ordered.entries()) {
          const row = rows.nth(index);
          await expect(row).toContainText(pin.source.component_type.split(".").join(" · "));
          await expect(row).toContainText(
            `Saved reference ${pin.position + 1} · Revision ${pin.revision}`,
          );
        }
        await expect(dock.getByTestId("karen-pins-empty")).toHaveCount(0);
      }
      await expect(dock.getByTestId("karen-pinning-not-available")).toHaveCount(0);
    } else {
      expect([401, 403, 404, 503]).toContain(contents.status);
      await expect(dock.getByTestId("karen-pinning-not-available")).toBeVisible();
      await expect(dock.getByTestId("karen-pins-authorized")).toHaveCount(0);
    }
    await expect(dock.getByTestId("karen-pins-loading")).toHaveCount(0);
  });
});


/**
 * KUI-002D3M: genuinely authenticated and disposable backend mutation trial.
 *
 * This test deliberately exercises the canonical HTTP mutation transport:
 * the real consumer dock is still release-gated and must show no controls.
 * Only an approved two-principal environment with TWO already persisted,
 * authorized and disposable pins may opt in. Do not seed sources, mock calls,
 * change production flags, or run against a normal user account.
 */
const mutationEnabled = process.env.KAREN_PIN_MUTATION_ACCEPTANCE === "1";
const secondPinId = process.env.KAREN_PIN_MUTATION_SECOND_PIN_ID;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type LivePin = { pin_id: string; position: number; revision: number };
type LivePins = { schema_version: number; read_only: boolean; pins: LivePin[] };
type LiveResponse = { status: number; cache: string | null; body: unknown };

async function livePinRequest(
  page: import("@playwright/test").Page,
  operation: "GET" | "POST",
  path: "/api/chat/ag-ui/pins" | "/api/chat/ag-ui/pins/capabilities" |
    "/api/chat/ag-ui/pins/mutations",
  payload?: Record<string, unknown>,
): Promise<LiveResponse> {
  return page.evaluate(async ({ operation, path, payload }) => {
    const token = window.localStorage.getItem("access_token");
    const headers: Record<string, string> = token
      ? { Authorization: `Bearer ${token}` } : {};
    if (operation === "POST") headers["Content-Type"] = "application/json";
    const response = await window.fetch(path, {
      method: operation,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers,
      ...(operation === "POST" ? { body: JSON.stringify(payload) } : {}),
    });
    let body: unknown = null;
    try { body = await response.json(); } catch { /* No fabricated result. */ }
    return {
      status: response.status,
      cache: response.headers.get("cache-control"),
      body,
    };
  }, { operation, path, payload });
}

function verifiedLivePins(response: LiveResponse): LivePin[] {
  expect(response.status).toBe(200);
  expect(response.cache).toContain("no-store");
  const snapshot = response.body as LivePins;
  expect(snapshot.schema_version).toBe(1);
  expect(snapshot.read_only).toBe(true);
  expect(Array.isArray(snapshot.pins)).toBe(true);
  expect(new Set(snapshot.pins.map(pin => pin.pin_id)).size).toBe(snapshot.pins.length);
  expect(new Set(snapshot.pins.map(pin => pin.position)).size).toBe(snapshot.pins.length);
  for (const pin of snapshot.pins) {
    expect(uuidPattern.test(pin.pin_id)).toBe(true);
    expect(Number.isSafeInteger(pin.position) && pin.position >= 0).toBe(true);
    expect(Number.isSafeInteger(pin.revision) && pin.revision >= 1).toBe(true);
  }
  return snapshot.pins;
}

test("KPIN-MUTATION-LIVE: authenticated dual-account denial, revision CAS and committed reorder", async (
  { page, browser },
) => {
  test.skip(!mutationEnabled, "Requires approved disposable PostgreSQL pin mutation trial");
  test.setTimeout(6 * 60_000);
  if (!email || !password || !foreignEmail || !foreignPassword ||
      !expectedPinId || !secondPinId || !uuidPattern.test(expectedPinId) ||
      !uuidPattern.test(secondPinId) || secondPinId === expectedPinId ||
      email.trim().toLowerCase() === foreignEmail.trim().toLowerCase()) {
    throw new Error("Two distinct authenticated accounts and two distinct disposable owned pin UUIDs required");
  }

  await signInApprovedKaren(page, email, password);
  await page.goto("/dashboard");
  const dock = page.getByTestId("karen-copilot-pinned-dock");
  await expect(dock).toBeVisible();
  await expect(dock.getByTestId("karen-pin-controls")).toHaveCount(0);

  const capability = await livePinRequest(page, "GET", "/api/chat/ag-ui/pins/capabilities");
  expect(capability.status).toBe(200);
  expect(capability.cache).toContain("no-store");
  expect(capability.body).toMatchObject({
    schema_version: 1,
    mutation_enabled: true,
    allowed_operations: expect.arrayContaining(["unpin", "reorder"]),
    denial_reason: null,
  });

  const before = verifiedLivePins(
    await livePinRequest(page, "GET", "/api/chat/ag-ui/pins"),
  );
  const moving = before.find(pin => pin.pin_id === expectedPinId);
  const neighbor = before.find(pin => pin.pin_id === secondPinId);
  expect(moving, "Owner pin must be freshly admitted").toBeDefined();
  expect(neighbor, "Distinct disposable adjacent pin must be admitted").toBeDefined();
  if (!moving || !neighbor) throw new Error("Disposable pins are not admitted");
  expect(before.map(pin => pin.position).sort((a, b) => a - b)).toEqual(
    before.map((_, i) => i),
  );
  expect(Math.abs(moving.position - neighbor.position)).toBe(1);

  // Browser.newContext does not inherit the Playwright project's baseURL.
  // Bind the second principal to the exact approved origin, never a mock host.
  const approvedOriginValue = process.env.KAREN_BASE_URL;
  if (!approvedOriginValue) {
    throw new Error("Protected pin acceptance requires an approved HTTPS origin");
  }
  const approvedOrigin = new URL(approvedOriginValue);
  if (approvedOrigin.protocol !== "https:" || approvedOrigin.username ||
      approvedOrigin.password || approvedOrigin.port ||
      approvedOrigin.pathname !== "/" || approvedOrigin.search || approvedOrigin.hash) {
    throw new Error("Protected pin acceptance requires a credential-free HTTPS origin");
  }
  const otherContext = await browser.newContext({
    baseURL: approvedOrigin.origin,
    viewport: { width: 1720, height: 980 },
    serviceWorkers: "block",
  });
  try {
    // Share only independently attested first-party deployment protection,
    // never the owner's application session or authentication cookie.
    const deploymentCookies = (await page.context().cookies(approvedOrigin.origin))
      .filter(cookie => cookie.name === "_vercel_jwt" && cookie.secure &&
        cookie.domain.replace(/^\./, "") === approvedOrigin.hostname);
    if (approvedOrigin.hostname.endsWith(".vercel.app") &&
        deploymentCookies.length !== 1) {
      throw new Error("Approved isolated browser deployment access missing");
    }
    if (deploymentCookies.length) {
      await otherContext.addCookies(deploymentCookies);
    }
    const foreign = await otherContext.newPage();
    await signInApprovedKaren(foreign, foreignEmail, foreignPassword);
    await foreign.goto("/dashboard");
    const foreignPins = verifiedLivePins(
      await livePinRequest(foreign, "GET", "/api/chat/ag-ui/pins"),
    );
    expect(foreignPins.some(pin => pin.pin_id === moving.pin_id)).toBe(false);
    const denied = await livePinRequest(
      foreign, "POST", "/api/chat/ag-ui/pins/mutations",
      {
        operation: "reorder",
        idempotency_key: crypto.randomUUID(),
        pin_id: moving.pin_id,
        expected_revision: moving.revision,
        position: moving.position,
      },
    );
    expect([403, 404, 409]).toContain(denied.status);
  } finally {
    await otherContext.close();
  }

  // Two genuine simultaneous HTTP requests compete for the same scoped row
  // and revision. Neither request is mocked, retried, or optimistically
  // applied by the browser. Distinct keys prohibit replay conflation.
  const intendedPosition = neighbor.position;
  const firstKey = crypto.randomUUID();
  const secondKey = crypto.randomUUID();
  const request = {
    operation: "reorder",
    idempotency_key: firstKey,
    pin_id: moving.pin_id,
    expected_revision: moving.revision,
    position: intendedPosition,
  };
  const competing = { ...request, idempotency_key: secondKey };
  const responses = await Promise.all([
    livePinRequest(page, "POST", "/api/chat/ag-ui/pins/mutations", request),
    livePinRequest(page, "POST", "/api/chat/ag-ui/pins/mutations", competing),
  ]);
  expect(responses.map(result => result.status).sort((a, b) => a - b))
    .toEqual([200, 409]);
  const winnerIndex = responses.findIndex(result => result.status === 200);
  expect(winnerIndex).toBeGreaterThanOrEqual(0);
  const winningKey = winnerIndex === 0 ? firstKey : secondKey;
  const winningRequest = winnerIndex === 0 ? request : competing;
  const committed = responses[winnerIndex];
  expect(committed.cache).toContain("no-store");
  expect(committed.body).toMatchObject({
    schema_version: 1,
    committed: true,
    receipt: {
      idempotency_key: winningKey,
      operation: "reorder",
      pin_id: moving.pin_id,
    },
  });
  // The committed operation must be retry-safe even after the other
  // concurrent transaction failed; a new key with an old revision must not.
  const replay = await livePinRequest(
    page, "POST", "/api/chat/ag-ui/pins/mutations", winningRequest,
  );
  expect(replay.status).toBe(200);
  expect(replay.body).toEqual(committed.body);

  const after = verifiedLivePins(
    await livePinRequest(page, "GET", "/api/chat/ag-ui/pins"),
  );
  expect(after.find(pin => pin.pin_id === moving.pin_id)?.position).toBe(intendedPosition);
  expect(after.find(pin => pin.pin_id === moving.pin_id)?.revision).toBeGreaterThan(
    moving.revision,
  );
  expect(after.map(pin => pin.position).sort((a, b) => a - b)).toEqual(
    after.map((_, i) => i),
  );

  const stale = await livePinRequest(page, "POST", "/api/chat/ag-ui/pins/mutations", {
    ...request,
    idempotency_key: crypto.randomUUID(),
  });
  expect(stale.status, "Stale revision must not commit a second reorder").toBe(409);

  await page.reload();
  await expect(dock).toBeVisible();
  const restored = verifiedLivePins(
    await livePinRequest(page, "GET", "/api/chat/ag-ui/pins"),
  );
  expect(restored.find(pin => pin.pin_id === moving.pin_id)?.position).toBe(intendedPosition);
  await expect(dock.getByTestId("karen-pin-controls")).toHaveCount(0);
});
