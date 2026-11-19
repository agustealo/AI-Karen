import { type Page, type TestInfo } from "@playwright/test";
import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * Real authenticated File Explorer acceptance. No mocked routes, files,
 * authentication or plugin availability. The source is the live owner-scoped
 * ArtifactStore behind /api/plugins/file-explorer/inventory.
 *
 * Opt-in: KAREN_FILE_EXPLORER_ACCEPTANCE=true
 * Local loopback requires KAREN_LOCAL_CHAT_ACCEPTANCE=1.
 * Requires a dedicated, sanitized account and an enabled File Explorer plugin.
 * To prove a second real page, seed >100 genuinely owned artifacts beforehand
 * and set KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE=true.
 */
const enabled = process.env.KAREN_FILE_EXPLORER_ACCEPTANCE === "true";
const requireSecondPage =
  process.env.KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;

const widths = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

interface Source {
  source_id: string;
  parent_id: null;
  kind: "file";
  name: string;
  revision: string;
  size_bytes: number;
  sha256: string;
}
interface Inventory {
  items: Source[];
  has_more: boolean;
  next_cursor: string | null;
  inventory_semantics: "owner_metadata_page_not_live_acl";
  request_id: string;
  correlation_id: string;
}

test.use({ trace: "off", video: "off", screenshot: "off" });

function trustedOrigin(): URL {
  const value = process.env.KAREN_BASE_URL;
  if (!value) throw new Error("KAREN_BASE_URL is required");
  const url = new URL(value);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Refusing credentials for non-origin URL");
  }
  const local = url.protocol === "http:" &&
    (url.hostname === "127.0.0.1" || url.hostname === "localhost") &&
    Boolean(url.port) && process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
  const secure = url.protocol === "https:" && !url.port;
  if (!local && !secure) {
    throw new Error("Only reviewed HTTPS or opted-in local loopback is allowed");
  }
  return url;
}

function inventoryResponse(raw: unknown): Inventory {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Real inventory response is not an object");
  }
  const data = raw as Record<string, unknown>;
  if (!Array.isArray(data.items) || data.items.length > 200 ||
      typeof data.has_more !== "boolean" ||
      data.inventory_semantics !== "owner_metadata_page_not_live_acl" ||
      typeof data.request_id !== "string" || !data.request_id ||
      typeof data.correlation_id !== "string" || !data.correlation_id ||
      (data.has_more ? typeof data.next_cursor !== "string" ||
        !data.next_cursor || data.items.length === 0 : data.next_cursor !== null)) {
    throw new Error("Real inventory metadata contract is invalid");
  }
  const seen = new Set<string>();
  for (const entry of data.items) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("Real file inventory entry is malformed");
    }
    const file = entry as Record<string, unknown>;
    if (typeof file.source_id !== "string" || seen.has(file.source_id) ||
        file.kind !== "file" || file.parent_id !== null ||
        typeof file.name !== "string" || !file.name || file.name.length > 256 ||
        typeof file.revision !== "string" || !/^[a-f0-9]{64}$/.test(file.revision) ||
        file.revision !== file.sha256 ||
        typeof file.size_bytes !== "number" || !Number.isSafeInteger(file.size_bytes) || file.size_bytes < 0) {
      throw new Error("Real file inventory item violates the source contract");
    }
    seen.add(file.source_id);
  }
  return data as unknown as Inventory;
}

async function nextRealPage(page: Page, target: URL) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === "/api/plugins/file-explorer/inventory" &&
      response.request().method() === "GET";
  }, { timeout: 45_000 });
}

async function verifyDisplayedInventory(page: Page, inventory: Inventory) {
  const explorer = page.getByRole("region", { name: "Shared File Explorer" });
  await expect(explorer).toBeVisible();
  const entries = explorer.getByRole("list", { name: "Files and folders" });
  if (inventory.items.length === 0) {
    await expect(explorer.getByText("No files or folders in this view.")).toBeVisible();
  } else {
    await expect(entries.getByRole("listitem")).toHaveCount(inventory.items.length);
    const pageNames = await entries.getByRole("listitem").allTextContents();
    for (const artifact of inventory.items) {
      expect(
        pageNames.some((value) => value.includes(artifact.name)),
        "A real inventory source must be visible: " + artifact.source_id,
      ).toBe(true);
    }
  }
  await expect(explorer.getByText(
    new RegExp(`\\b${inventory.items.length} shown on this page\\b`),
  )).toBeVisible();
  if (inventory.has_more) {
    await expect(explorer.getByRole("button", { name: "Next page" })).toBeEnabled();
  } else {
    await expect(explorer.getByRole("button", { name: "Next page" })).toHaveCount(0);
  }
}

async function enterWorkspace(page: Page) {
  const advanced = page.getByRole("button", { name: "Advanced tools" }).last();
  if (!(await advanced.isVisible().catch(() => false))) {
    const toggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(toggle).toBeVisible();
    await toggle.click();
  }
  await expect(advanced).toBeVisible();
  if ((await advanced.getAttribute("aria-expanded")) !== "true") {
    await advanced.click();
  }
  const workspace = page.getByRole("button", { name: "File Explorer", exact: true }).last();
  await expect(workspace, "A real enabled plugin must appear in the catalog").toBeVisible();
  await workspace.click();
}

test("KFILE-LIVE: authenticated owner files, pagination, refresh, layout and keyboard", async (
  { page }, info: TestInfo,
) => {
  test.skip(!enabled, "Requires KAREN_FILE_EXPLORER_ACCEPTANCE=true");
  test.setTimeout(6 * 60_000);
  if (!email || !password) {
    throw new Error("Dedicated KAREN_UX_EMAIL / KAREN_UX_PASSWORD required");
  }
  const origin = trustedOrigin();
  await page.setViewportSize(widths[0]);
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1",
  });

  const inventoryRequest = nextRealPage(page, origin);
  await enterWorkspace(page);
  const response = await inventoryRequest;
  expect(response.status(), "Real owner inventory must authorize HTTP 200").toBe(200);
  const firstPage = inventoryResponse(await response.json());
  expect(firstPage.items.length, "Acceptance requires a genuine owned artifact").toBeGreaterThan(0);
  await verifyDisplayedInventory(page, firstPage);

  const explorer = page.getByRole("region", { name: "Shared File Explorer" });
  for (const viewport of widths) {
    await page.setViewportSize(viewport);
    await expect(explorer).toBeVisible();
    const geometry = await explorer.evaluate((node) => {
      const bounds = node.getBoundingClientRect();
      return {
        viewportWidth: document.documentElement.clientWidth,
        pageWidth: document.documentElement.scrollWidth,
        left: bounds.left,
        right: bounds.right,
      };
    });
    expect(geometry.pageWidth, `Unexpected sideways overflow at ${viewport.width}px`)
      .toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.left).toBeGreaterThanOrEqual(-1);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    await verifyDisplayedInventory(page, firstPage);
  }

  await page.setViewportSize(widths[0]);
  const filter = explorer.getByRole("searchbox", { name: "Filter current folder" });
  await filter.focus();
  await expect(filter).toBeFocused();
  await filter.fill(firstPage.items[0].name);
  await expect(explorer.getByRole("listitem")).toHaveCount(
    firstPage.items.filter((item) => item.name.toLowerCase().includes(firstPage.items[0].name.toLowerCase())).length,
  );
  await filter.fill("");

  if (requireSecondPage) {
    expect(firstPage.has_more, "A real second page was required but no cursor exists").toBe(true);
  }
  if (firstPage.has_more) {
    const next = nextRealPage(page, origin);
    await explorer.getByRole("button", { name: "Next page" }).click();
    const secondResponse = await next;
    expect(secondResponse.status()).toBe(200);
    const secondPage = inventoryResponse(await secondResponse.json());
    expect(secondPage.items.length).toBeGreaterThan(0);
    expect(secondPage.items.every((item) =>
      !firstPage.items.some((older) => older.source_id === item.source_id),
    ), "Keyset pages must not repeat owner file IDs").toBe(true);
    await verifyDisplayedInventory(page, secondPage);
  }

  const refresh = nextRealPage(page, origin);
  await explorer.getByRole("button", { name: "Refresh" }).click();
  const refreshedResponse = await refresh;
  expect(refreshedResponse.status()).toBe(200);
  const refreshed = inventoryResponse(await refreshedResponse.json());
  await verifyDisplayedInventory(page, refreshed);

  // A read-only acceptance run never uploads, changes ACLs or disables plugins.
  expect(info.project.name).toBe("chromium");
});
