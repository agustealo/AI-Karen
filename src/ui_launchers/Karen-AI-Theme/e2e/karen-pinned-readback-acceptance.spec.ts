import { expect, test } from "@playwright/test";
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
