import { randomUUID } from "node:crypto";
import { type Page, type Request, type TestInfo } from "@playwright/test";
import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * Real authenticated File Explorer acceptance. No mocked routes, files,
 * authentication or plugin availability. The source is the live owner-scoped
 * ArtifactStore behind /api/plugins/file-explorer/hierarchy.
 *
 * Opt-in: KAREN_FILE_EXPLORER_ACCEPTANCE=true
 * Local loopback requires KAREN_LOCAL_CHAT_ACCEPTANCE=1.
 * Requires a dedicated, sanitized account and an enabled File Explorer plugin.
 * To prove a second real page, seed >100 genuinely owned artifacts beforehand
 * and set KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE=true.
 * Protected File Explorer acceptance also requires a root folder containing
 * a child folder with at least one owned file, and a root artifact with a
 * printable ASCII filename (1–160 characters) for literal search evidence.
 * The first root folder and its first child must satisfy this fixture contract.
 * No fixture is created by this read-only test.
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
  parent_id: string | null;
  kind: "file";
  name: string;
  revision: string;
  size_bytes: number;
  sha256: string;
  organization_revision: string;
}
interface Folder {
  folder_id: string;
  parent_folder_id: string | null;
  name: string;
  revision: string;
}
interface Inventory {
  items: Source[];
  has_more: boolean;
  next_cursor: string | null;
  folders: Folder[];
  breadcrumbs: Folder[];
  folders_has_more: boolean;
  next_folder_id: string | null;
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

const uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const validRevision = (value: unknown): value is string => typeof value === "string" &&
  /^[1-9][0-9]{0,18}$/.test(value) && (value.length < 19 || value <= "9223372036854775806");

function inventoryResponse(raw: unknown, parent: string | null = null): Inventory {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Real hierarchy response is not an object");
  }
  const data = raw as Record<string, unknown>;
  if (data.available !== true || !Array.isArray(data.files) || data.files.length > 100 ||
      !Array.isArray(data.folders) || data.folders.length > 100 ||
      !Array.isArray(data.breadcrumbs) || data.breadcrumbs.length > 64 ||
      typeof data.has_more !== "boolean" || typeof data.files_has_more !== "boolean" ||
      typeof data.request_id !== "string" || !data.request_id ||
      typeof data.correlation_id !== "string" || !data.correlation_id ||
      (data.files_has_more ? typeof data.next_file_cursor !== "string" ||
        !data.next_file_cursor || data.next_file_cursor.length > 768 || data.files.length === 0 :
        data.next_file_cursor !== null) ||
      (data.has_more ? typeof data.next_folder_id !== "string" ||
        !uuidPattern.test(data.next_folder_id) || data.folders.length === 0 :
        data.next_folder_id !== null)) {
    throw new Error("Real hierarchy metadata contract is invalid");
  }
  const seen = new Set<string>();
  function checkFolder(rawFolder: unknown, expectedParent: string | null): Folder {
    if (!rawFolder || typeof rawFolder !== "object" || Array.isArray(rawFolder)) {
      throw new Error("Malformed folder evidence");
    }
    const folder = rawFolder as Record<string, unknown>;
    if (typeof folder.folder_id !== "string" || !uuidPattern.test(folder.folder_id) ||
        seen.has(folder.folder_id) || folder.folder_id === expectedParent ||
        folder.parent_folder_id !== expectedParent ||
        typeof folder.name !== "string" || !folder.name || folder.name.length > 256 ||
        !validRevision(folder.revision)) throw new Error("Invalid folder evidence");
    seen.add(folder.folder_id);
    return folder as unknown as Folder;
  }
  let prior: string | null = null;
  const breadcrumbs = data.breadcrumbs.map(crumb => {
    const folder = checkFolder(crumb, prior);
    prior = folder.folder_id;
    return folder;
  });
  if (prior !== parent) throw new Error("Breadcrumb chain does not end at requested parent");
  const folders = data.folders.map(folder => checkFolder(folder, parent));
  if (data.has_more && folders[folders.length - 1]?.folder_id !== data.next_folder_id) {
    throw new Error("Folder pagination anchor is not the last returned folder");
  }
  for (const entry of data.files) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("Real file inventory entry is malformed");
    }
    const file = entry as Record<string, unknown>;
    if (typeof file.source_id !== "string" || !uuidPattern.test(file.source_id) || seen.has(file.source_id) ||
        file.kind !== "file" || file.parent_id !== parent ||
        typeof file.name !== "string" || !file.name || file.name.length > 256 ||
        typeof file.revision !== "string" || !/^[a-f0-9]{64}$/.test(file.revision) ||
        file.revision !== file.sha256 || !validRevision(file.organization_revision) ||
        typeof file.size_bytes !== "number" || !Number.isSafeInteger(file.size_bytes) || file.size_bytes < 0) {
      throw new Error("Real file inventory item violates the source contract");
    }
    seen.add(file.source_id);
  }
  return { items: data.files as Source[], folders, breadcrumbs,
    has_more: data.files_has_more, next_cursor: data.next_file_cursor as string | null,
    folders_has_more: data.has_more, next_folder_id: data.next_folder_id as string | null,
    request_id: data.request_id, correlation_id: data.correlation_id };
}

async function nextRealPage(page: Page, target: URL) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === "/api/plugins/file-explorer/hierarchy" &&
      response.request().method() === "GET";
  }, { timeout: 45_000 });
}

async function nextRealAnalysis(page: Page, target: URL) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === target.origin &&
      url.pathname === '/api/plugins/content-intelligence/owner-sources' &&
      response.request().method() === 'POST';
  }, { timeout: 45_000 });
}

async function verifyDisplayedInventory(page: Page, inventory: Inventory, search = '') {
  const explorer = page.getByRole("region", { name: "Shared File Explorer" });
  await expect(explorer).toBeVisible();
  const entries = explorer.getByRole("list", { name: "Files and folders" });
  const count = inventory.items.length + inventory.folders.length;
  if (count === 0) {
    await expect(explorer.getByText(search ? "No matching files or folders on this search page." : "No files or folders in this view.")).toBeVisible();
  } else {
    await expect(entries.getByRole("listitem")).toHaveCount(count);
    for (const folder of inventory.folders) {
      await expect(entries.getByRole('button', { name: 'Open folder ' + folder.name, exact: true }).first()).toBeVisible();
    }
    const pageNames = await entries.getByRole("listitem").allTextContents();
    for (const artifact of inventory.items) {
      expect(
        pageNames.some((value) => value.includes(artifact.name)),
        "A real inventory source must be visible: " + artifact.source_id,
      ).toBe(true);
    }
  }
  await expect(explorer.getByText(
    new RegExp(`\\b${count} shown on this page\\b`),
  )).toBeVisible();
  if (inventory.has_more) {
    await expect(explorer.getByRole("button", { name: "Next file page" })).toBeEnabled();
  } else {
    await expect(explorer.getByRole("button", { name: "Next file page" })).toHaveCount(0);
  }
  if (inventory.folders_has_more) {
    await expect(explorer.getByRole('button', { name: 'Next folder page' })).toBeEnabled();
  } else {
    await expect(explorer.getByRole('button', { name: 'Next folder page' })).toHaveCount(0);
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
  const firstFileCheckbox = explorer.getByRole("list", { name: "Files and folders" })
    .getByRole("checkbox").first();
  await expect(firstFileCheckbox).not.toBeChecked();
  await firstFileCheckbox.check();
  await expect(firstFileCheckbox).toBeChecked();
  await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();
  // Layout controls are presentation-only. Exercise both actual render modes
  // at every required viewport, preserving the already selected reference.
  const layoutGroup = explorer.getByRole("group", { name: "Explorer layout" });
  const selectedLabel = await firstFileCheckbox.getAttribute("aria-label");
  if (!selectedLabel) throw new Error("Selected file has no accessible name");
  const selectedCheckbox = explorer.getByRole("checkbox", { name: selectedLabel, exact: true }).first();
  for (const viewport of widths) {
    await page.setViewportSize(viewport);
    for (const mode of ["grid", "list"] as const) {
      const control = layoutGroup.getByRole("button", { name: mode === "grid" ? "Grid view" : "List view" });
      await control.focus();
      await expect(control).toBeFocused();
      await control.press("Space");
      await expect(control).toHaveAttribute("aria-pressed", "true");
      await expect(explorer.getByRole("list", { name: "Files and folders" }))
        .toHaveCSS("display", mode === "grid" ? "grid" : "flex");
      const geometry = await explorer.evaluate((node) => {
        const bounds = node.getBoundingClientRect();
        return {
          viewportWidth: document.documentElement.clientWidth,
          pageWidth: document.documentElement.scrollWidth,
          left: bounds.left,
          right: bounds.right,
        };
      });
      expect(geometry.pageWidth, `Unexpected sideways overflow at ${viewport.width}px (${mode})`)
        .toBeLessThanOrEqual(geometry.viewportWidth + 1);
      expect(geometry.left).toBeGreaterThanOrEqual(-1);
      expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 1);
      await verifyDisplayedInventory(page, firstPage);
      await expect(selectedCheckbox).toBeChecked();
      await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();
    }
  }

  await page.setViewportSize(widths[0]);
  const filter = explorer.getByRole("searchbox", { name: "Filter current folder" });
  await filter.focus();
  await expect(filter).toBeFocused();
  await filter.fill(firstPage.items[0].name);
  await expect(explorer.getByRole("listitem")).toHaveCount(
    [...firstPage.items, ...firstPage.folders].filter((item) => item.name.toLowerCase().includes(firstPage.items[0].name.toLowerCase())).length,
  );
  await filter.fill("");

  // Local filtering must not silently remove an already selected reference.
  let noMatch = "__kexp_no_match__";
  while ([...firstPage.items, ...firstPage.folders].some(item =>
    item.name.toLowerCase().includes(noMatch))) noMatch += "_";
  await filter.fill(noMatch);
  await expect(selectedCheckbox).toHaveCount(0);
  await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();
  await explorer.getByRole("button", { name: "Review selection (1)", exact: true }).click();
  const review = explorer.getByRole("list", { name: "Selected references" });
  await expect(review.getByRole("listitem")).toHaveCount(1);
  await expect(review.getByRole("button", { name: "Remove " + selectedLabel.slice("Select ".length) + " from selection", exact: true })).toBeVisible();
  await explorer.getByRole("button", { name: "Review selection (1)", exact: true }).click();
  await filter.fill("");
  await expect(selectedCheckbox).toBeChecked();

  if (requireSecondPage) {
    expect(firstPage.has_more, "A real second page was required but no cursor exists").toBe(true);
  }
  if (firstPage.has_more) {
    const next = nextRealPage(page, origin);
    await explorer.getByRole("button", { name: "Next file page" }).click();
    const secondResponse = await next;
    expect(secondResponse.status()).toBe(200);
    const cursorSent = new URL(secondResponse.request().url()).searchParams.get("file_cursor");
    expect(cursorSent, "The UI must forward the precise backend-owned cursor").toBe(firstPage.next_cursor);
    const secondPage = inventoryResponse(await secondResponse.json());
    expect(secondPage.items.length).toBeGreaterThan(0);
    expect(secondPage.items.every((item) =>
      !firstPage.items.some((older) => older.source_id === item.source_id),
    ), "Keyset pages must not repeat owner file IDs").toBe(true);
    await verifyDisplayedInventory(page, secondPage);
    await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
    const secondFileCheckbox = explorer.getByRole("list", { name: "Files and folders" })
      .getByRole("checkbox").first();
    await secondFileCheckbox.check();
    await expect(secondFileCheckbox).toBeChecked();
    await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();
  }

  const refresh = nextRealPage(page, origin);
  await explorer.getByRole("button", { name: "Refresh" }).click();
  const refreshedResponse = await refresh;
  expect(refreshedResponse.status()).toBe(200);
  expect(new URL(refreshedResponse.request().url()).searchParams.has("file_cursor"),
    "Refresh must request a fresh first owner page, not retain the old cursor").toBe(false);
  const refreshed = inventoryResponse(await refreshedResponse.json());
  await verifyDisplayedInventory(page, refreshed);
  await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
  if (refreshed.items.length > 0) {
    await expect(explorer.getByRole("list", { name: "Files and folders" })
      .getByRole("checkbox").first()).not.toBeChecked();
  }

  // A real server search is distinct from filtering already-loaded rows.
  // Use an observed owner filename, not a fabricated positive fixture.
  const searchSource = refreshed.items.find(file =>
    /^[\x20-\x7e]{1,160}$/.test(file.name) && file.name.trim() === file.name);
  expect(searchSource, "Seed an owned root file with a printable ASCII filename of at most 160 characters").toBeDefined();
  if (!searchSource) throw new Error("No eligible real search fixture");
  const query = searchSource.name.toLowerCase();
  await explorer.getByRole("checkbox", { name: "Select " + searchSource.name, exact: true }).first().check();
  const searchInput = explorer.getByRole("searchbox", { name: "Search filenames in this folder" });
  await searchInput.fill(query);
  const searchWait = nextRealPage(page, origin);
  await explorer.getByRole("form", { name: "Search authorized filenames" }).getByRole("button", { name: "Search", exact: true }).click();
  const searchHttp = await searchWait;
  expect(searchHttp.status()).toBe(200);
  const searchParams = new URL(searchHttp.request().url()).searchParams;
  expect(searchParams.get("search")).toBe(query);
  expect(searchParams.has("file_cursor")).toBe(false);
  expect(searchParams.has("parent_folder_id")).toBe(false);
  const searched = inventoryResponse(await searchHttp.json());
  expect(searched.items.some(file => file.source_id === searchSource.source_id)).toBe(true);
  expect(searched.items.every(file => file.name.toLowerCase().includes(query))).toBe(true);
  expect(searched.folders.map(folder => folder.folder_id)).toEqual(refreshed.folders.map(folder => folder.folder_id));
  await verifyDisplayedInventory(page, searched, query);
  await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
  await expect(explorer.getByRole("searchbox", { name: "Search filenames in this folder" })).toHaveValue(query);

  if (searched.has_more) {
    const searchNext = nextRealPage(page, origin);
    await explorer.getByRole("button", { name: "Next file page" }).click();
    const nextHttp = await searchNext;
    expect(nextHttp.status()).toBe(200);
    const nextParams = new URL(nextHttp.request().url()).searchParams;
    expect(nextParams.get("search")).toBe(query);
    expect(nextParams.get("file_cursor")).toBe(searched.next_cursor);
    const nextSearched = inventoryResponse(await nextHttp.json());
    expect(nextSearched.items.every(file => file.name.toLowerCase().includes(query) &&
      !searched.items.some(earlier => earlier.source_id === file.source_id))).toBe(true);
    await verifyDisplayedInventory(page, nextSearched, query);
  }

  const clearWait = nextRealPage(page, origin);
  await explorer.getByRole("button", { name: "Clear search", exact: true }).click();
  const clearHttp = await clearWait;
  expect(clearHttp.status()).toBe(200);
  const clearParams = new URL(clearHttp.request().url()).searchParams;
  expect(clearParams.has("search")).toBe(false);
  expect(clearParams.has("file_cursor")).toBe(false);
  const cleared = inventoryResponse(await clearHttp.json());
  await verifyDisplayedInventory(page, cleared);
  await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
  await expect(explorer.getByRole("searchbox", { name: "Search filenames in this folder" })).toHaveValue("");

  // Observe real nested navigation when a sanitized fixture exists.
  // The protected fixture may explicitly require nested proof; absence is not a pass.
  const requireNested = process.env.KAREN_FILE_EXPLORER_REQUIRE_NESTED === "true";
  if (requireNested) {
    expect(cleared.folders.length, "A real root folder fixture is required").toBeGreaterThan(0);
  }
  if (cleared.folders.length > 0) {
    const folder = cleared.folders[0];
    const next = nextRealPage(page, origin);
    await explorer.getByRole("button", { name: "Open folder " + folder.name, exact: true }).first().click();
    const nestedHttp = await next;
    expect(nestedHttp.status()).toBe(200);
    expect(new URL(nestedHttp.request().url()).searchParams.get("parent_folder_id")).toBe(folder.folder_id);
    const nested = inventoryResponse(await nestedHttp.json(), folder.folder_id);
    await verifyDisplayedInventory(page, nested);
    await expect(explorer.getByRole("navigation", { name: "Folder location" })
      .getByRole("button", { name: folder.name, exact: true }).last()).toHaveAttribute("aria-current", "location");
    await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
    if (requireNested) {
      expect(nested.folders.length, "The first root folder must contain a real child folder").toBeGreaterThan(0);
    }
    if (nested.folders.length > 0) {
      const child = nested.folders[0];
      const childWait = nextRealPage(page, origin);
      await explorer.getByRole("button", { name: "Open folder " + child.name, exact: true }).first().click();
      const childHttp = await childWait;
      expect(childHttp.status()).toBe(200);
      expect(new URL(childHttp.request().url()).searchParams.get("parent_folder_id")).toBe(child.folder_id);
      const childPage = inventoryResponse(await childHttp.json(), child.folder_id);
      expect(childPage.breadcrumbs.map(crumb => crumb.folder_id)).toEqual([folder.folder_id, child.folder_id]);
      await verifyDisplayedInventory(page, childPage);
      if (requireNested) {
        expect(childPage.items.length, "The first child folder must contain a real owned file").toBeGreaterThan(0);
      }
      if (childPage.items.length > 0) {
        const childFile = explorer.getByRole("list", { name: "Files and folders" }).getByRole("checkbox").first();
        await childFile.check();
        await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();
      }
      const parentWait = nextRealPage(page, origin);
      const location = explorer.getByRole("navigation", { name: "Folder location" });
      await expect(location.getByRole("button").nth(1)).toHaveText(folder.name);
      await location.getByRole("button").nth(1).click();
      const parentHttp = await parentWait;
      expect(parentHttp.status()).toBe(200);
      expect(new URL(parentHttp.request().url()).searchParams.get("parent_folder_id")).toBe(folder.folder_id);
      await verifyDisplayedInventory(page, inventoryResponse(await parentHttp.json(), folder.folder_id));
      await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
    }
    const back = nextRealPage(page, origin);
    await explorer.getByRole("navigation", { name: "Folder location" }).getByRole("button", { name: "Root", exact: true }).first().click();
    const rootHttp = await back;
    expect(rootHttp.status()).toBe(200);
    expect(new URL(rootHttp.request().url()).searchParams.has("parent_folder_id")).toBe(false);
    await verifyDisplayedInventory(page, inventoryResponse(await rootHttp.json()));
  }

  // A read-only acceptance run never uploads, changes ACLs or disables plugins.
  expect(info.project.name).toBe("chromium");
});


/**
 * Explicitly local, disposable organization proof. Never included in the
 * protected read-only KFILE-LIVE dispatch. The operator must verify that the
 * local web/API/database stack is isolated from production before opting in.
 * Only changes synthetic child folders inside one named fixture.
 * No automatic retry, upload or existing-file mutation.
 */
test("KFILE-MUTATION-LOCAL: confirmed organization and deletion recovery", async ({ page, browser }) => {
  test.skip(!enabled || process.env.KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE !== "true",
    "Requires explicit local disposable mutation acceptance");
  test.setTimeout(6 * 60_000);
  if (process.env.KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE !== "true" ||
      process.env.KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true") {
    throw new Error("Explicit deletion opt-in and isolated backend attestation required");
  }
  const origin = trustedOrigin();
  if (origin.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(origin.hostname) ||
      process.env.KAREN_LOCAL_CHAT_ACCEPTANCE !== "1" ||
      process.env.GITHUB_ACTIONS === "true" ||
      process.env.VERCEL_AUTOMATION_BYPASS_SECRET !== undefined) {
    throw new Error("Organization mutation acceptance requires an isolated local loopback stack");
  }
  const fixtureId = process.env.KAREN_FILE_EXPLORER_MUTATION_FIXTURE_ID;
  const fixtureName = "KEXP-005B-disposable";
  if (!fixtureId || !uuidPattern.test(fixtureId) || !email || !password) {
    throw new Error("Explicit disposable fixture UUID and sanitized owner credentials required");
  }
  const nonce = randomUUID();
  const sourceName = "kexp-source-" + nonce;
  const renamedName = "kexp-renamed-" + nonce;
  const destinationName = "kexp-destination-" + nonce;
  const prefix = "/api/plugins/file-explorer";
  const writes: string[] = [];
  function observeWrites(actor: Page) {
    actor.on("request", request => {
      const url = new URL(request.url());
      if (url.origin === origin.origin && url.pathname.startsWith(prefix + "/") &&
          ["POST", "PATCH", "DELETE", "PUT"].includes(request.method())) {
        writes.push(request.method() + " " + url.pathname);
      }
    });
  }
  observeWrites(page);
  await signInApprovedKaren(page, email, password, { allowLocalLoopback: true });
  const rootWait = nextRealPage(page, origin);
  await enterWorkspace(page);
  const rootHttp = await rootWait;
  expect(rootHttp.status()).toBe(200);
  const root = inventoryResponse(await rootHttp.json());
  // Names are only used for UI activation after binding to the real UUID.
  const fixtures = root.folders.filter(folder => folder.name === fixtureName);
  expect(fixtures.length, "Exactly one disposable root fixture must be visible").toBe(1);
  expect(fixtures[0].folder_id === fixtureId, "Disposable fixture identity must match").toBe(true);
  const explorer = page.getByRole("region", { name: "Shared File Explorer" });
  const entries = explorer.getByRole("list", { name: "Files and folders" });
  const editor = explorer.getByRole("form", { name: "Confirm organization change" });
  const fixtureWait = nextRealPage(page, origin);
  await entries.getByRole("button", { name: "Open folder " + fixtureName, exact: true }).click();
  const fixtureHttp = await fixtureWait;
  expect(fixtureHttp.status()).toBe(200);
  const initial = inventoryResponse(await fixtureHttp.json(), fixtureId);
  expect(initial.folders.length + initial.items.length, "Use a fresh empty disposable fixture").toBe(0);
  expect(initial.has_more || initial.folders_has_more).toBe(false);
  await verifyDisplayedInventory(page, initial);

  function inventoryWait(parent: string, actor: Page = page) {
    return actor.waitForResponse(response => {
      const url = new URL(response.url());
      return url.origin === origin.origin && url.pathname === prefix + "/hierarchy" &&
        response.request().method() === "GET" && url.searchParams.get("parent_folder_id") === parent &&
        !url.searchParams.has("file_cursor") && !url.searchParams.has("after_folder_id") &&
        !url.searchParams.has("search");
    }, { timeout: 45_000 });
  }
  async function confirm(action: "create" | "rename" | "move" | "delete",
    method: "POST" | "PATCH" | "DELETE", path: string,
    payload: Record<string, unknown>, status: number, parent: string = fixtureId!,
    actor: Page = page) {
    const actorExplorer = actor.getByRole("region", { name: "Shared File Explorer" });
    const actorEditor = actorExplorer.getByRole("form", { name: "Confirm organization change" });
    const [http, reload] = await Promise.all([
      actor.waitForResponse(response => {
        const url = new URL(response.url());
        return url.origin === origin.origin && url.pathname === path && response.request().method() === method;
      }, { timeout: 45_000 }),
      inventoryWait(parent, actor),
      actorEditor.getByRole("button", { name: "Confirm " + action, exact: true }).click(),
    ]);
    expect(http.status()).toBe(status);
    expect(http.request().postDataJSON()).toEqual(payload);
    const receipt = await http.json();
    if (status === 409) {
      expect(receipt.detail).toBe("Folder nonempty, unavailable or revision conflicting");
    } else {
      expect(typeof receipt.request_id === "string" && Boolean(receipt.request_id)).toBe(true);
      expect(typeof receipt.correlation_id === "string" && Boolean(receipt.correlation_id)).toBe(true);
    }
    expect(reload.status()).toBe(200);
    const inventory = inventoryResponse(await reload.json(), parent);
    await verifyDisplayedInventory(actor, inventory);
    await expect(actorExplorer.getByText(status === 409
      ? "Organization conflict. Review the refreshed inventory before trying again."
      : "Organization change confirmed. Reloading inventory.", { exact: true })).toBeVisible();
    await expect(actorEditor).toHaveCount(0);
    return { receipt, inventory };
  }
  const createButton = explorer.getByRole("button", { name: "New folder", exact: true });
  // A cancelled editor must not submit a mutation; focus returns to its opener.
  await expect(createButton).toBeEnabled();
  await createButton.click();
  await expect(editor.getByRole("textbox", { name: "Folder name" })).toBeFocused();
  await editor.getByRole("textbox", { name: "Folder name" }).fill(sourceName);
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(createButton).toBeFocused();
  expect(writes).toHaveLength(0);

  async function create(name: string): Promise<Folder> {
    await expect(createButton).toBeEnabled();
    await createButton.click();
    await editor.getByRole("textbox", { name: "Folder name" }).fill(name);
    const { receipt, inventory } = await confirm("create", "POST", prefix + "/folders",
      { name, parent_folder_id: fixtureId }, 201);
    const folder = inventory.folders.find(item => item.name === name);
    if (!folder) throw new Error("Created folder missing from authoritative inventory");
    expect(folder.revision).toBe("1");
    expect(receipt.folder).toEqual(folder);
    return folder;
  }
  const source = await create(sourceName);
  const destination = await create(destinationName);
  expect(source.folder_id !== destination.folder_id).toBe(true);

  await entries.getByRole("button", { name: "Rename " + sourceName, exact: true }).click();
  await editor.getByRole("textbox", { name: "Folder name" }).fill(renamedName);
  const renamedResult = await confirm("rename", "PATCH", prefix + "/folders/" + source.folder_id,
    { name: renamedName, expected_revision: source.revision }, 200);
  const renamed = renamedResult.inventory.folders.find(folder => folder.folder_id === source.folder_id);
  if (!renamed) throw new Error("Renamed folder missing from authoritative inventory");
  expect(renamed.name).toBe(renamedName);
  expect(renamed.revision).toBe((BigInt(source.revision) + BigInt(1)).toString());
  expect(renamedResult.receipt.folder).toEqual(renamed);

  await entries.getByRole("button", { name: "Move " + renamedName, exact: true }).click();
  const destinationBrowser = editor.getByRole("region", { name: "Move destination browser" });
  await destinationBrowser.getByRole("button", { name: "Browse destination " + fixtureName, exact: true }).click();
  await destinationBrowser.getByRole("button", { name: "Browse destination " + destinationName, exact: true }).click();
  await expect(destinationBrowser.getByText("Selected destination: " + destinationName, { exact: true })).toBeVisible();
  const moved = await confirm("move", "POST", prefix + "/move/folder/" + source.folder_id,
    { destination_id: destination.folder_id, expected_revision: renamed.revision }, 200);
  const movedRevision = (BigInt(renamed.revision) + BigInt(1)).toString();
  expect(moved.receipt).toMatchObject({
    source_id: source.folder_id, kind: "folder", parent_folder_id: destination.folder_id,
    organization_revision: movedRevision,
  });
  expect(moved.inventory.folders.some(folder => folder.folder_id === source.folder_id)).toBe(false);
  const currentDestination = moved.inventory.folders.find(folder => folder.folder_id === destination.folder_id);
  if (!currentDestination) throw new Error("Destination missing from authoritative inventory");
  // A confirmed nonempty deletion must not cascade or modify either folder.
  await entries.getByRole("button", { name: "Delete " + destinationName, exact: true }).click();
  await expect(editor).toBeFocused();
  await expect(editor.getByText("Delete " + destinationName + "? Only empty folders can be deleted, including no archived files. File contents will not be deleted.", { exact: true })).toBeVisible();
  const nonempty = await confirm("delete", "DELETE", prefix + "/folders/" + destination.folder_id,
    { expected_revision: currentDestination.revision }, 409);
  expect(nonempty.inventory.folders).toEqual(moved.inventory.folders);
  expect(nonempty.inventory.items).toEqual([]);
  const [destinationHttp] = await Promise.all([
    inventoryWait(destination.folder_id),
    entries.getByRole("button", { name: "Open folder " + destinationName, exact: true }).click(),
  ]);
  expect(destinationHttp.status()).toBe(200);
  const readback = inventoryResponse(await destinationHttp.json(), destination.folder_id);
  expect(readback.folders).toEqual([{
    folder_id: source.folder_id, name: renamedName,
    parent_folder_id: destination.folder_id, revision: movedRevision,
  }]);
  expect(readback.items.length).toBe(0);
  await verifyDisplayedInventory(page, readback);
  const deleteButton = entries.getByRole("button", { name: "Delete " + renamedName, exact: true });
  await deleteButton.click();
  await expect(editor).toBeFocused();
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(deleteButton).toBeFocused();
  expect(writes).toHaveLength(5);

  // Retain the first browser's observed revision while another authenticated
  // context renames the generated child using the same governed UI.
  await deleteButton.click();
  const concurrentName = "kexp-conflict-" + nonce;
  const second = await browser.newContext({ baseURL: origin.origin, serviceWorkers: "block" });
  let currentChild: Folder;
  try {
    const other = await second.newPage();
    observeWrites(other);
    await signInApprovedKaren(other, email, password, { allowLocalLoopback: true });
    const [otherRootHttp] = await Promise.all([nextRealPage(other, origin), enterWorkspace(other)]);
    expect(otherRootHttp.status()).toBe(200);
    const otherRoot = inventoryResponse(await otherRootHttp.json());
    expect(otherRoot.folders.filter(folder => folder.name === fixtureName).map(folder => folder.folder_id))
      .toEqual([fixtureId]);
    const otherEntries = other.getByRole("region", { name: "Shared File Explorer" })
      .getByRole("list", { name: "Files and folders" });
    const [otherFixtureHttp] = await Promise.all([
      inventoryWait(fixtureId, other),
      otherEntries.getByRole("button", { name: "Open folder " + fixtureName, exact: true }).click(),
    ]);
    expect(otherFixtureHttp.status()).toBe(200);
    const otherFixture = inventoryResponse(await otherFixtureHttp.json(), fixtureId);
    expect(otherFixture.folders).toEqual(nonempty.inventory.folders);
    expect(otherFixture.items).toEqual([]);
    const [otherDestinationHttp] = await Promise.all([
      inventoryWait(destination.folder_id, other),
      otherEntries.getByRole("button", { name: "Open folder " + destinationName, exact: true }).click(),
    ]);
    expect(otherDestinationHttp.status()).toBe(200);
    const otherDestination = inventoryResponse(await otherDestinationHttp.json(), destination.folder_id);
    expect(otherDestination.folders).toEqual(readback.folders);
    expect(otherDestination.items).toEqual([]);
    await otherEntries.getByRole("button", { name: "Rename " + renamedName, exact: true }).click();
    await other.getByRole("form", { name: "Confirm organization change" })
      .getByRole("textbox", { name: "Folder name" }).fill(concurrentName);
    const changed = await confirm("rename", "PATCH", prefix + "/folders/" + source.folder_id,
      { name: concurrentName, expected_revision: movedRevision }, 200, destination.folder_id, other);
    const observed = changed.inventory.folders.find(folder => folder.folder_id === source.folder_id);
    if (!observed) throw new Error("Concurrent rename missing from inventory");
    currentChild = observed;
    expect(currentChild).toEqual({
      folder_id: source.folder_id, parent_folder_id: destination.folder_id,
      name: concurrentName, revision: (BigInt(movedRevision) + BigInt(1)).toString(),
    });
    expect(changed.receipt.folder).toEqual(currentChild);
  } finally {
    await second.close();
  }
  // A real stale confirmation must return conflict and must not automatically
  // issue a new delete using the refreshed revision.
  const stale = await confirm("delete", "DELETE", prefix + "/folders/" + source.folder_id,
    { expected_revision: movedRevision }, 409, destination.folder_id);
  expect(stale.inventory.folders).toEqual([currentChild]);
  expect(stale.inventory.items).toEqual([]);
  expect(writes).toHaveLength(7);
  await expect(entries.getByRole("button", { name: "Delete " + renamedName, exact: true })).toHaveCount(0);

  const [childHttp] = await Promise.all([
    inventoryWait(source.folder_id),
    entries.getByRole("button", { name: "Open folder " + concurrentName, exact: true }).click(),
  ]);
  expect(childHttp.status()).toBe(200);
  const childInventory = inventoryResponse(await childHttp.json(), source.folder_id);
  expect(childInventory.folders).toEqual([]);
  expect(childInventory.items).toEqual([]);
  expect(childInventory.has_more || childInventory.folders_has_more).toBe(false);
  const [backHttp] = await Promise.all([
    inventoryWait(destination.folder_id),
    explorer.getByRole("navigation", { name: "Folder location" })
      .getByRole("button", { name: destinationName, exact: true }).click(),
  ]);
  expect(backHttp.status()).toBe(200);
  const beforeDelete = inventoryResponse(await backHttp.json(), destination.folder_id);
  expect(beforeDelete.folders).toEqual([currentChild]);
  expect(beforeDelete.items).toEqual([]);
  await entries.getByRole("button", { name: "Delete " + concurrentName, exact: true }).click();
  const deleted = await confirm("delete", "DELETE", prefix + "/folders/" + source.folder_id,
    { expected_revision: currentChild.revision }, 200, destination.folder_id);
  expect(deleted.receipt).toMatchObject({ deleted: true, folder_id: source.folder_id });
  expect(deleted.inventory.folders).toEqual([]);
  expect(deleted.inventory.items).toEqual([]);
  expect(deleted.inventory.has_more || deleted.inventory.folders_has_more).toBe(false);
  expect(writes).toEqual([
    "POST " + prefix + "/folders", "POST " + prefix + "/folders",
    "PATCH " + prefix + "/folders/" + source.folder_id,
    "POST " + prefix + "/move/folder/" + source.folder_id,
    "DELETE " + prefix + "/folders/" + destination.folder_id,
    "PATCH " + prefix + "/folders/" + source.folder_id,
    "DELETE " + prefix + "/folders/" + source.folder_id,
    "DELETE " + prefix + "/folders/" + source.folder_id,
  ]);
  // Keep the generated destination for inspection; never guess at cleanup
  // after a failed or uncertain receipt. The operator resets locally.
});

/**
 * Dedicated local consumer draft proof. No model execution is authorized.
 * The fixture must be blank and have 13 uniquely named real root files.
 * All draft writes go through the mounted consumer composer.
 */
test("KFILE-ATTACHMENT-LOCAL: capacity, saved references and blocked submission", async ({ page }) => {
  test.skip(!enabled || process.env.KAREN_FILE_EXPLORER_ATTACHMENT_ACCEPTANCE !== "true",
    "Requires explicit local attachment acceptance");
  test.setTimeout(6 * 60_000);
  const origin = trustedOrigin();
  if (origin.protocol !== "http:" || process.env.GITHUB_ACTIONS === "true" ||
      process.env.VERCEL_AUTOMATION_BYPASS_SECRET !== undefined ||
      process.env.KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true") {
    throw new Error("Attachment acceptance requires an attested isolated local stack");
  }
  const conversationId = process.env.KAREN_FILE_EXPLORER_ATTACHMENT_CONVERSATION_ID;
  const conversationTitle = process.env.KAREN_FILE_EXPLORER_ATTACHMENT_CONVERSATION_TITLE;
  if (!conversationId || !uuidPattern.test(conversationId) || !conversationTitle || !email || !password) {
    throw new Error("Explicit sanitized conversation UUID, title and owner credentials required");
  }
  const draftPath = "/api/conversations/" + conversationId + "/draft";
  const draftUrl = new URL(draftPath + "?include_attachments=true", origin).toString();
  const marker = "KEXP-005D unsent " + randomUUID();
  type Reference = { source_id: string; revision: string };
  type Draft = { text: string; revision: number; attachment_references: Reference[] };
  let runs = 0;
  let organizationWrites = 0;
  let observedDraftRequest: Request | undefined;
  page.context().on("request", request => {
    const url = new URL(request.url());
    // Observe the mounted composer's real authenticated transport. A
    // Playwright API request alone does not inherit its bearer header.
    if (url.origin === origin.origin && url.pathname === draftPath &&
        ["GET", "PUT"].includes(request.method())) observedDraftRequest = request;
    if (request.method() === "POST" &&
        (url.pathname === "/api/copilotkit/agent/default/run" ||
        ["/api/chat/ag-ui", "/api/chat/stream", "/api/chat"].includes(url.pathname))) runs++;
    if (url.pathname.startsWith("/api/plugins/file-explorer/") &&
        ["POST", "PATCH", "PUT", "DELETE"].includes(request.method())) organizationWrites++;
  });
  await signInApprovedKaren(page, email, password, { allowLocalLoopback: true });
  const workspace = page.getByTestId("karen-copilot-consumer-chat");
  const candidate = workspace.getByTestId("karen-copilot-controlled-chat");
  const composer = candidate.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
  const attachments = candidate.getByRole("region", { name: "Draft attachments" });
  const browse = candidate.getByRole("button", { name: "Browse files", exact: true });
  async function openConversation() {
    await expect(workspace).toBeVisible({ timeout: 30_000 });
    if (await workspace.getAttribute("data-conversation-id") !== conversationId) {
      await workspace.getByRole("button", { name: "Find conversations" }).click();
      await workspace.getByPlaceholder("Search conversation titles").fill(conversationTitle!);
      const match = workspace.getByRole("group", { name: "Matching conversations" })
        .locator('button[data-conversation-id="' + conversationId + '"]');
      await expect(match).toHaveCount(1);
      await match.click();
    }
    await expect(workspace).toHaveAttribute("data-conversation-id", conversationId!);
    await expect(composer).toBeVisible({ timeout: 30_000 });
  }
  await openConversation();
  async function readDraft(): Promise<Draft> {
    await expect.poll(() => Boolean(observedDraftRequest), { timeout: 15_000 }).toBe(true);
    const headers = await observedDraftRequest!.allHeaders();
    const authorization = headers.authorization;
    if (!authorization && !headers.cookie) {
      throw new Error("Canonical draft transport has no observed authentication");
    }
    const response = await page.request.get(draftUrl, {
      headers: authorization ? { authorization } : undefined,
      maxRedirects: 0, maxRetries: 0,
    });
    expect(response.status()).toBe(200);
    const value = await response.json() as Draft;
    expect(Number.isSafeInteger(value.revision) && value.revision >= 0).toBe(true);
    expect(typeof value.text).toBe("string");
    expect(Array.isArray(value.attachment_references)).toBe(true);
    return value;
  }
  const initial = await readDraft();
  expect(initial.text, "Only an empty disposable draft can be modified").toBe("");
  expect(initial.attachment_references).toEqual([]);
  await expect(composer).toHaveValue("");
  await expect(attachments).toHaveCount(0);
  async function saved(text: string, refs: Reference[], previous: number) {
    await expect.poll(async () => {
      const current = await readDraft();
      return { text: current.text, refs: current.attachment_references, advanced: current.revision > previous };
    }, { timeout: 20_000 }).toEqual({ text, refs, advanced: true });
    return readDraft();
  }
  const inventoryPromise = nextRealPage(page, origin);
  await browse.click();
  const http = await inventoryPromise;
  expect(http.status()).toBe(200);
  const inventory = inventoryResponse(await http.json());
  const files = inventory.items.filter(file => inventory.items.filter(item => item.name === file.name).length === 1);
  expect(files.length, "Seed at least 13 uniquely named real root artifacts").toBeGreaterThanOrEqual(13);
  const chosen = files.slice(0, 13);
  const references = chosen.slice(0, 12).map(({ source_id, revision }) => ({ source_id, revision }));
  const browserRegion = candidate.getByRole("region", { name: "Conversation file browser" });
  const explorer = browserRegion.getByRole("region", { name: "Shared File Explorer" });
  const select = (file: Source) => explorer.getByRole("checkbox", { name: "Select " + file.name, exact: true });
  await expect(browserRegion.getByText("12 additional file references available.", { exact: true })).toBeVisible();
  await composer.fill(marker);
  const typed = await saved(marker, [], initial.revision);
  await select(chosen[0]).check();
  await browserRegion.getByRole("button", { name: "Attach selected files (1)", exact: true }).click();
  const first = await saved(marker, references.slice(0, 1), typed.revision);
  await expect(attachments.getByText("References saved", { exact: true })).toBeVisible();
  await expect(select(chosen[0])).toHaveCount(0);
  await expect(browserRegion.getByText("11 additional file references available.", { exact: true })).toBeVisible();
  for (const file of chosen.slice(1, 12)) await select(file).check();
  await expect(select(chosen[12])).toBeDisabled();
  await browserRegion.getByRole("button", { name: "Attach selected files (11)", exact: true }).click();
  const full = await saved(marker, references, first.revision);
  await expect(attachments.getByText("12 / 12 file references", { exact: true })).toBeVisible();
  await expect(attachments.getByText("References saved", { exact: true })).toBeVisible();
  await expect(browserRegion.getByText("0 additional file references available.", { exact: true })).toBeVisible();
  await expect(select(chosen[12])).toBeDisabled();
  await browse.click();
  await expect(browserRegion).toHaveCount(0);
  observedDraftRequest = undefined;
  await page.reload();
  await openConversation();
  await expect(composer).toHaveValue(marker);
  await expect(attachments.getByText("References saved", { exact: true })).toBeVisible();
  for (const ref of references) {
    await expect(attachments.getByRole("button", { name: "Remove file reference " + ref.source_id })).toBeVisible();
  }
  expect(await readDraft()).toEqual(full);

  // The SDK send gesture is explicitly denied while references exist.
  await composer.press("Enter");
  await expect(candidate.getByRole("alert")).toContainText("Sending attached files is not supported yet.");
  await expect(composer).toHaveValue(marker);
  await expect(attachments.getByText("References saved", { exact: true })).toBeVisible();
  expect(await readDraft()).toEqual(full);
  expect(runs).toBe(0);

  await attachments.getByRole("button", { name: "Remove file reference " + references[0].source_id }).click();
  const removed = await saved(marker, references.slice(1), full.revision);
  await expect(attachments.getByText("11 / 12 file references", { exact: true })).toBeVisible();
  const reopened = nextRealPage(page, origin);
  await browse.click();
  expect((await reopened).status()).toBe(200);
  await expect(browserRegion.getByText("1 additional file references available.", { exact: true })).toBeVisible();
  await expect(select(chosen[0])).toBeEnabled();
  await select(chosen[12]).check();
  await expect(select(chosen[0])).toBeDisabled();
  await browserRegion.getByRole("button", { name: "Attach selected files (1)", exact: true }).click();
  const replaced = [...references.slice(1), { source_id: chosen[12].source_id, revision: chosen[12].revision }];
  await saved(marker, replaced, removed.revision);
  await expect(attachments.getByText("References saved", { exact: true })).toBeVisible();
  expect(runs, "Draft operations must never execute inference").toBe(0);
  expect(organizationWrites, "Draft attachment selection must never mutate files").toBe(0);
  // Retain only this disposable draft for inspection. Never clear an uncertain
  // receipt or another user's draft automatically.
});

/**
 * Real local principal/tenant transition and revoked-credential admission.
 * Two distinct sanitized tenants, preseeded files, folders and drafts.
 * No setup writes; the only mutation probes request an unchanged folder name.
 * Never use a real customer's credentials or objects.
 */
test("KFILE-ISOLATION-LOCAL: cross-tenant owner inventory and revoked session denial", async ({ page, browser }) => {
  test.skip(!enabled || process.env.KAREN_FILE_EXPLORER_ISOLATION_ACCEPTANCE !== "true",
    "Requires explicit local isolation acceptance");
  test.setTimeout(6 * 60_000);
  const origin = trustedOrigin();
  if (origin.protocol !== "http:" || process.env.GITHUB_ACTIONS === "true" ||
      process.env.VERCEL_AUTOMATION_BYPASS_SECRET !== undefined ||
      process.env.KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true") {
    throw new Error("Isolation acceptance requires an attested isolated local stack");
  }
  const otherEmail = process.env.KAREN_UX_ISOLATION_EMAIL;
  const otherPassword = process.env.KAREN_UX_ISOLATION_PASSWORD;
  const aSource = process.env.KAREN_FILE_EXPLORER_ISOLATION_A_SOURCE_ID;
  const bSource = process.env.KAREN_FILE_EXPLORER_ISOLATION_B_SOURCE_ID;
  const aFolder = process.env.KAREN_FILE_EXPLORER_ISOLATION_A_FOLDER_ID;
  const bFolder = process.env.KAREN_FILE_EXPLORER_ISOLATION_B_FOLDER_ID;
  const aDraft = process.env.KAREN_FILE_EXPLORER_ISOLATION_A_CONVERSATION_ID;
  const bDraft = process.env.KAREN_FILE_EXPLORER_ISOLATION_B_CONVERSATION_ID;
  const ids = [aSource, bSource, aFolder, bFolder, aDraft, bDraft];
  if (!email || !password || !otherEmail || !otherPassword ||
      email.trim().toLowerCase() === otherEmail.trim().toLowerCase() ||
      ids.some(id => !id || !uuidPattern.test(id)) || new Set(ids).size !== ids.length) {
    throw new Error("Two distinct sanitized accounts and six distinct fixture UUIDs required");
  }
  await page.setViewportSize(widths[3]);
  const prefix = "/api/plugins/file-explorer";
  const endpoint = (path: string) => new URL(path, origin).toString();
  const draftUrl = (id: string) => endpoint("/api/conversations/" + id + "/draft?include_attachments=true");
  const explorer = page.getByRole("region", { name: "Shared File Explorer" });
  // A separate cookie-free transport makes a replay a real test of the
  // observed access credential, not merely a test of an empty cookie jar.
  const replay = await browser.newContext({ baseURL: origin.origin, serviceWorkers: "block" });
  type Identity = { user_id: string; tenant_id: string };
  async function inspectActor(sourceId: string, folderId: string, foreignSource: string, foreignFolder: string) {
    const pending = nextRealPage(page, origin);
    await enterWorkspace(page);
    const http = await pending;
    expect(http.status()).toBe(200);
    const inventory = inventoryResponse(await http.json());
    expect(inventory.items.some(file => file.source_id === foreignSource)).toBe(false);
    expect(inventory.folders.some(folder => folder.folder_id === foreignFolder)).toBe(false);
    const file = inventory.items.find(item => item.source_id === sourceId);
    const folder = inventory.folders.find(item => item.folder_id === folderId);
    if (!file || !folder) throw new Error("Dedicated owned fixtures must be on the first root page");
    expect(inventory.items.filter(item => item.name === file.name)).toHaveLength(1);
    expect(inventory.folders.filter(item => item.name === folder.name)).toHaveLength(1);
    await verifyDisplayedInventory(page, inventory);
    await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
    // Observe the exact browser credential, without reading local storage,
    // printing headers or exporting browser state. Require a bearer so the
    // independent replay can prove both pre-revocation and post-revocation.
    const observed = await http.request().allHeaders();
    const authorization = observed.authorization;
    if (!authorization || !/^Bearer \S+$/.test(authorization)) {
      throw new Error("A real observed bearer credential is required for revocation proof");
    }
    const options = { headers: { authorization }, maxRedirects: 0, maxRetries: 0 };
    const identityHttp = await replay.request.get(endpoint("/api/auth/me"), options);
    expect(identityHttp.status()).toBe(200);
    const identity = await identityHttp.json() as Identity;
    expect(Boolean(identity.user_id && identity.tenant_id)).toBe(true);
    const control = await replay.request.get(endpoint(prefix + "/hierarchy"), options);
    expect(control.status()).toBe(200);
    const controlInventory = inventoryResponse(await control.json());
    expect(controlInventory.items.some(item => item.source_id === sourceId)).toBe(true);
    expect(controlInventory.folders.some(item => item.folder_id === folderId)).toBe(true);
    await expect(explorer.getByRole("button", { name: "Rename " + folder.name, exact: true })).toBeEnabled();
    return { file, folder, identity, options };
  }
  async function verifyOwnDraft(id: string, actor: Awaited<ReturnType<typeof inspectActor>>, foreignId: string) {
    const response = await replay.request.get(draftUrl(id), actor.options);
    expect(response.status()).toBe(200);
    const body = await response.json() as { revision: number; attachment_references: { source_id: string; revision: string }[] };
    expect(Number.isSafeInteger(body.revision)).toBe(true);
    expect(Array.isArray(body.attachment_references)).toBe(true);
    expect(body.attachment_references).toContainEqual({ source_id: actor.file.source_id, revision: actor.file.revision });
    expect(body.attachment_references.some(ref => ref.source_id === foreignId)).toBe(false);
  }
  try {
    await signInApprovedKaren(page, email, password, { allowLocalLoopback: true });
    const owner = await inspectActor(aSource!, aFolder!, bSource!, bFolder!);
    await verifyOwnDraft(aDraft!, owner, bSource!);
    await explorer.getByRole("checkbox", { name: "Select " + owner.file.name, exact: true }).check();
    await expect(explorer.getByText(/\b1 selected\b/)).toBeVisible();

    await page.getByRole("button", { name: "My Account", exact: true }).last().click();
    const logout = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.origin === origin.origin && url.pathname === "/api/auth/logout" && response.request().method() === "POST";
    }, { timeout: 30_000 });
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    expect((await logout).ok()).toBe(true);
    await expect(page).toHaveURL(/\/login(?:[/?#]|$)/, { timeout: 30_000 });
    await expect(explorer).toHaveCount(0);

    // Replay the same credential that succeeded before logout, on the same
    // independent transport. A login redirect or anonymous 401 is not proof.
    await replay.clearCookies();
    const revokedInventory = await replay.request.get(endpoint(prefix + "/hierarchy"), owner.options);
    expect([401, 403]).toContain(revokedInventory.status());
    await replay.clearCookies();
    const revokedDraft = await replay.request.get(draftUrl(aDraft!), owner.options);
    expect([401, 403]).toContain(revokedDraft.status());
    await replay.clearCookies();
    const revokedRename = await replay.request.patch(endpoint(prefix + "/folders/" + owner.folder.folder_id), {
      ...owner.options, data: { name: owner.folder.name, expected_revision: owner.folder.revision },
    });
    expect([401, 403]).toContain(revokedRename.status());

    await signInApprovedKaren(page, otherEmail, otherPassword, { allowLocalLoopback: true });
    const other = await inspectActor(bSource!, bFolder!, aSource!, aFolder!);
    expect(other.identity.user_id === owner.identity.user_id).toBe(false);
    expect(other.identity.tenant_id === owner.identity.tenant_id, "Fixtures must belong to different verified tenants").toBe(false);
    expect(other.file.name === owner.file.name).toBe(false);
    expect(other.folder.name === owner.folder.name).toBe(false);
    await expect(explorer.getByRole("checkbox", { name: "Select " + owner.file.name, exact: true })).toHaveCount(0);
    await expect(explorer.getByRole("button", { name: "Open folder " + owner.folder.name, exact: true })).toHaveCount(0);
    await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
    await verifyOwnDraft(bDraft!, other, aSource!);

    await replay.clearCookies();
    const foreignDraft = await replay.request.get(draftUrl(aDraft!), other.options);
    expect(foreignDraft.status()).toBe(404);
    await replay.clearCookies();
    const foreignRename = await replay.request.patch(endpoint(prefix + "/folders/" + owner.folder.folder_id), {
      ...other.options, data: { name: owner.folder.name, expected_revision: owner.folder.revision },
    });
    expect([403, 409]).toContain(foreignRename.status());

    // A new A login verifies that denial did not alter the fixture and that
    // the old credential remains revoked even after the principal returns.
    await page.getByRole("button", { name: "My Account", exact: true }).last().click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page).toHaveURL(/\/login(?:[/?#]|$)/, { timeout: 30_000 });
    await signInApprovedKaren(page, email, password, { allowLocalLoopback: true });
    const restored = await inspectActor(aSource!, aFolder!, bSource!, bFolder!);
    expect(restored.identity).toEqual(owner.identity);
    expect(restored.folder).toEqual(owner.folder);
    expect(restored.file.revision).toBe(owner.file.revision);
    await verifyOwnDraft(aDraft!, restored, bSource!);
    await replay.clearCookies();
    const stillRevoked = await replay.request.get(endpoint(prefix + "/hierarchy"), owner.options);
    expect([401, 403]).toContain(stillRevoked.status());
  } finally {
    await replay.close();
  }
});

/**
 * Opt-in real selection-to-analysis evidence. The dedicated acceptance owner
 * must seed a supported, active text/code artifact on the first owner page,
 * enable both canonical plugins, and supply its exact UUID. No route mocking.
 * This opt-in gate is not considered satisfied when the test is skipped.
 */
test('KCONTENT-LIVE: selected owner text is analyzed by the authorized runtime', async (
  { page },
) => {
  test.skip(
    !enabled || process.env.KAREN_CONTENT_INTELLIGENCE_ACCEPTANCE !== 'true',
    'Requires authenticated Content Intelligence live acceptance setup',
  );
  test.setTimeout(6 * 60_000);
  if (!email || !password) {
    throw new Error('Dedicated KAREN_UX_EMAIL / KAREN_UX_PASSWORD required');
  }
  const expectedId = process.env.KAREN_CONTENT_INTELLIGENCE_SOURCE_ID;
  if (!expectedId || !/^[a-f0-9-]{36}$/.test(expectedId)) {
    throw new Error('Seeded KAREN_CONTENT_INTELLIGENCE_SOURCE_ID UUID required');
  }
  const origin = trustedOrigin();
  await page.setViewportSize(widths[0]);
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === '1',
  });

  const inventoryRequest = nextRealPage(page, origin);
  await enterWorkspace(page);
  const inventoryHttp = await inventoryRequest;
  expect(inventoryHttp.status()).toBe(200);
  const inventory = inventoryResponse(await inventoryHttp.json());
  const selected = inventory.items.find((file) => file.source_id === expectedId);
  expect(selected, 'Dedicated owned text artifact must appear in the live first page').toBeDefined();
  if (!selected) throw new Error('Selected owner artifact not available');

  const explorer = page.getByRole('region', { name: 'Shared File Explorer' });
  await verifyDisplayedInventory(page, inventory);
  await explorer.getByRole('checkbox', { name: 'Select ' + selected.name }).first().check();
  await expect(
    page.getByRole('button', { name: 'Analyze selected files' }),
  ).toBeEnabled();

  // Observe actual requests; a refresh must never execute analysis implicitly.
  let analysisPosts = 0;
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin === origin.origin &&
        url.pathname === '/api/plugins/content-intelligence/owner-sources' &&
        request.method() === 'POST') {
      analysisPosts += 1;
    }
  });
  const analysisHttpPromise = nextRealAnalysis(page, origin);
  await page.getByRole('button', { name: 'Analyze selected files' }).click();
  const analysisHttp = await analysisHttpPromise;
  const requestPayload = analysisHttp.request().postDataJSON();
  expect(requestPayload).toEqual({
    operation: 'analyze',
    references: [{ source_id: expectedId, revision: selected.sha256 }],
  });
  expect(analysisHttp.status(), 'Authorization or source reads must not silently degrade').toBe(200);
  const responseBody = await analysisHttp.json();
  expect(responseBody.operation).toBe('analyze');
  expect(responseBody.persisted).toBe(false);
  expect(responseBody.documents).toHaveLength(1);
  expect(responseBody.documents[0].id).toBe(expectedId);
  expect(responseBody.documents[0].sha256).toBe(selected.sha256);

  const verifiedResult = page.getByRole('status', { name: 'Verified analysis results' });
  await expect(verifiedResult).toBeVisible();
  await expect(verifiedResult.getByText(selected.name)).toBeVisible();
  await expect(verifiedResult.getByText(/Lexical analysis of 1 authorized file/)).toBeVisible();
  expect(analysisPosts).toBe(1);

  // KPLUG-09: browser refresh must discard previously shown content evidence
  // and the old selection. No source bytes, route stubs or Storage URLs enter
  // the browser test. Re-analysis requires a fresh source reference and click.
  const refreshResponse = nextRealPage(page, origin);
  await explorer.getByRole('button', { name: 'Refresh' }).click();
  const refreshedHttp = await refreshResponse;
  expect(refreshedHttp.status()).toBe(200);
  expect(new URL(refreshedHttp.request().url()).searchParams.has('file_cursor')).toBe(false);
  const refreshed = inventoryResponse(await refreshedHttp.json());
  const current = refreshed.items.find((file) => file.source_id === expectedId);
  expect(current, 'Approved source must remain owner-active for refresh proof').toBeDefined();
  if (!current) throw new Error('Refreshed source no longer eligible');
  await verifyDisplayedInventory(page, refreshed);
  await expect(explorer.getByText(/\b0 selected\b/)).toBeVisible();
  await expect(page.getByRole('status', { name: 'Verified analysis results' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Analyze selected files' })).toHaveCount(0);
  expect(analysisPosts, 'Refresh must never silently replay Content Intelligence').toBe(1);

  await explorer.getByRole('checkbox', { name: 'Select ' + current.name }).first().check();
  const secondAnalysisPromise = nextRealAnalysis(page, origin);
  await page.getByRole('button', { name: 'Analyze selected files' }).click();
  const secondAnalysisHttp = await secondAnalysisPromise;
  expect(secondAnalysisHttp.request().postDataJSON()).toEqual({
    operation: 'analyze',
    references: [{ source_id: expectedId, revision: current.sha256 }],
  });
  expect(secondAnalysisHttp.status()).toBe(200);
  const secondResult = await secondAnalysisHttp.json();
  expect(secondResult.persisted).toBe(false);
  expect(secondResult.documents).toHaveLength(1);
  expect(secondResult.documents[0].id).toBe(expectedId);
  expect(secondResult.documents[0].sha256).toBe(current.sha256);
  await expect(page.getByRole('status', { name: 'Verified analysis results' })).toBeVisible();
  expect(analysisPosts).toBe(2);
});


/**
 * Real, read-only negative authorization proof.
 *
 * Uses two separately authenticated sanitized users. All credentials stay in
 * GitHub environment secrets and never enter logs, snapshots or artifacts.
 * Both actors require functional plugins and data:read, so an HTTP 403 cannot
 * be mistaken for a missing/disabled plugin or unauthenticated request.
 */
test('KCONTENT-DENY-LIVE: foreign owner and stale revision fail closed', async (
  { page, browser },
) => {
  test.skip(
    !enabled || process.env.KAREN_CONTENT_INTELLIGENCE_DENIAL_ACCEPTANCE !== 'true',
    'Requires protected live Content Intelligence negative-authorization scenario',
  );
  test.setTimeout(6 * 60_000);
  const otherEmail = process.env.KAREN_UX_ISOLATION_EMAIL;
  const otherPassword = process.env.KAREN_UX_ISOLATION_PASSWORD;
  const sourceId = process.env.KAREN_CONTENT_INTELLIGENCE_SOURCE_ID;
  const otherSourceId = process.env.KAREN_CONTENT_INTELLIGENCE_ISOLATION_SOURCE_ID;
  if (!email || !password || !otherEmail || !otherPassword ||
      !sourceId || !/^[a-f0-9-]{36}$/.test(sourceId) ||
      !otherSourceId || !/^[a-f0-9-]{36}$/.test(otherSourceId) ||
      otherSourceId === sourceId ||
      otherEmail.trim().toLowerCase() === email.trim().toLowerCase()) {
    throw new Error('Two distinct sanitized users and an owned source UUID are required');
  }
  const origin = trustedOrigin();

  // Observed real owner inventory gives exact immutable source evidence.
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === '1',
  });
  const ownerInventoryPromise = nextRealPage(page, origin);
  await enterWorkspace(page);
  const ownerInventoryHttp = await ownerInventoryPromise;
  expect(ownerInventoryHttp.status()).toBe(200);
  const ownerInventory = inventoryResponse(await ownerInventoryHttp.json());
  const file = ownerInventory.items.find((item) => item.source_id === sourceId);
  expect(file, 'A real, active owned text/code source must be present').toBeDefined();
  if (!file) throw new Error('Owner source not present');

  // Reuse auth on a browser-origin request; do not manually read tokens.
  // A malformed revision is a legitimate reference shape but may not be read.
  const ownerHeaders = await ownerInventoryHttp.request().allHeaders();
  const auth = ownerHeaders.authorization;
  if (!auth && !ownerHeaders.cookie) {
    throw new Error('Unable to attest authenticated API transport');
  }
  const currentRevision = file.sha256;
  const analysisUrl = new URL('/api/plugins/content-intelligence/owner-sources', origin).toString();
  const ownerGood = await page.request.post(analysisUrl, {
    headers: auth ? { authorization: auth } : undefined,
    data: { operation: 'analyze', references: [{ source_id: sourceId, revision: currentRevision }] },
  });
  expect(ownerGood.status(), 'Owner must have successful Content Intelligence admission').toBe(200);
  const ownerBody = await ownerGood.json();
  expect(ownerBody.operation).toBe('analyze');
  expect(ownerBody.documents).toHaveLength(1);
  expect(ownerBody.documents[0].id).toBe(sourceId);
  expect(ownerBody.documents[0].sha256).toBe(currentRevision);

  const forgedRevision = (currentRevision[0] === 'a' ? 'b' : 'a') + currentRevision.slice(1);
  const ownerBad = await page.request.post(
    new URL('/api/plugins/content-intelligence/owner-sources', origin).toString(),
    {
      headers: auth ? { authorization: auth } : undefined,
      data: {
        operation: 'analyze',
        references: [{ source_id: sourceId, revision: forgedRevision }],
      },
    },
  );
  expect(ownerBad.status(), 'A forged owner revision must be denied').toBe(403);
  const ownerDenial = await ownerBad.text();
  expect(ownerDenial).not.toContain(file.name);
  expect(ownerDenial).not.toContain(file.sha256);
  expect(ownerDenial.length).toBeLessThan(2048);

  const isolated = await browser.newContext({
    baseURL: origin.toString(),
    serviceWorkers: 'block',
  });
  try {
    // Carry only the exact-host deployment protection cookie, never the
    // owner application's session, credentials or other cookies.
    const deploymentCookies = (await page.context().cookies(origin.origin))
      .filter((cookie) =>
        cookie.name === '_vercel_jwt' && cookie.secure &&
        cookie.domain.replace(/^\./, '') === origin.hostname,
      );
    if (origin.hostname.endsWith('.vercel.app') && deploymentCookies.length !== 1) {
      throw new Error('Approved isolated deployment access cookie is missing');
    }
    if (deploymentCookies.length) {
      await isolated.addCookies(deploymentCookies);
    }

    const otherPage = await isolated.newPage();
    await signInApprovedKaren(otherPage, otherEmail, otherPassword, {
      allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === '1',
    });
    const otherInventoryPromise = nextRealPage(otherPage, origin);
    await enterWorkspace(otherPage);
    const otherInventoryHttp = await otherInventoryPromise;
    expect(otherInventoryHttp.status(), 'Second account must have real inventory access').toBe(200);
    const otherInventory = inventoryResponse(await otherInventoryHttp.json());
    expect(otherInventory.items.some((item) => item.source_id === sourceId)).toBe(false);
    const otherFile = otherInventory.items.find((item) => item.source_id === otherSourceId);
    expect(otherFile, 'Second account must own a real supported text source').toBeDefined();
    if (!otherFile) throw new Error('Second owner source not present');

    const otherHeaders = await otherInventoryHttp.request().allHeaders();
    const otherAuth = otherHeaders.authorization;
    if (!otherAuth && !otherHeaders.cookie) {
      throw new Error('Unable to attest second-user authenticated API transport');
    }
    const otherGood = await otherPage.request.post(analysisUrl, {
      headers: otherAuth ? { authorization: otherAuth } : undefined,
      data: { operation: 'analyze', references: [{
        source_id: otherSourceId, revision: otherFile.sha256,
      }] },
    });
    expect(otherGood.status(), 'Second account must have successful Content Intelligence admission').toBe(200);
    const otherBody = await otherGood.json();
    expect(otherBody.operation).toBe('analyze');
    expect(otherBody.documents).toHaveLength(1);
    expect(otherBody.documents[0].id).toBe(otherSourceId);
    expect(otherBody.documents[0].sha256).toBe(otherFile.sha256);

    const foreign = await otherPage.request.post(
      new URL('/api/plugins/content-intelligence/owner-sources', origin).toString(),
      {
        headers: otherAuth ? { authorization: otherAuth } : undefined,
        data: {
          operation: 'analyze',
          references: [{ source_id: sourceId, revision: currentRevision }],
        },
      },
    );
    expect(foreign.status(), 'Other authenticated principal cannot read owner text').toBe(403);
    const denial = await foreign.text();
    expect(denial).not.toContain(file.name);
    expect(denial).not.toContain(file.sha256);
    expect(denial.length).toBeLessThan(2048);
  } finally {
    await isolated.close();
  }
});

/** Read-only live denial for an independently attested retired owner artifact. */
test('KCONTENT-REVOKED-LIVE: retired owner source remains unavailable', async ({ page }) => {
  test.skip(
    !enabled || process.env.KAREN_CONTENT_INTELLIGENCE_REVOCATION_ACCEPTANCE !== 'true',
    'Protected real revoked-source fixture required',
  );
  test.setTimeout(6 * 60_000);
  if (!email || !password) throw new Error('Sanitized owner credentials required');
  const activeId = process.env.KAREN_CONTENT_INTELLIGENCE_SOURCE_ID;
  const retiredId = process.env.KAREN_CONTENT_INTELLIGENCE_REVOKED_SOURCE_ID;
  const retiredRevision = process.env.KAREN_CONTENT_INTELLIGENCE_REVOKED_REVISION;
  if (!activeId || !retiredId || !/^[a-f0-9-]{36}$/.test(activeId) ||
      !/^[a-f0-9-]{36}$/.test(retiredId) || activeId === retiredId ||
      !retiredRevision || !/^[a-f0-9]{64}$/.test(retiredRevision)) {
    throw new Error('Distinct active and independently attested retired source required');
  }
  const origin = trustedOrigin();
  await signInApprovedKaren(page, email, password, {
    allowLocalLoopback: process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === '1',
  });
  const inventoryWait = nextRealPage(page, origin);
  await enterWorkspace(page);
  const inventoryHttp = await inventoryWait;
  expect(inventoryHttp.status()).toBe(200);
  const inventory = inventoryResponse(await inventoryHttp.json());
  const active = inventory.items.find((item) => item.source_id === activeId);
  expect(active, 'Active owner source must be present').toBeDefined();
  if (!active) throw new Error('Active source control unavailable');
  expect(inventory.items.some((item) => item.source_id === retiredId)).toBe(false);
  const observedHeaders = await inventoryHttp.request().allHeaders();
  if (!observedHeaders.authorization && !observedHeaders.cookie) {
    throw new Error('Owner API transport is not authenticated');
  }
  const url = new URL('/api/plugins/content-intelligence/owner-sources', origin).toString();
  const headers = observedHeaders.authorization
    ? { authorization: observedHeaders.authorization } : undefined;
  const control = await page.request.post(url, {
    headers,
    data: { operation: 'analyze', references: [
      { source_id: activeId, revision: active.sha256 },
    ] },
  });
  expect(control.status(), 'Active owner analysis must succeed').toBe(200);
  const result = await control.json();
  expect(result.operation).toBe('analyze');
  expect(result.persisted).toBe(false);
  expect(result.documents).toHaveLength(1);
  expect(result.documents[0].id).toBe(activeId);
  expect(result.documents[0].sha256).toBe(active.sha256);

  const denied = await page.request.post(url, {
    headers,
    data: { operation: 'analyze', references: [
      { source_id: retiredId, revision: retiredRevision },
    ] },
  });
  expect(denied.status(), 'Independently attested retired source must be denied').toBe(403);
  const responseText = await denied.text();
  expect(responseText.length).toBeLessThan(2048);
  expect(responseText).not.toContain(retiredId);
  expect(responseText).not.toContain(retiredRevision);
});
