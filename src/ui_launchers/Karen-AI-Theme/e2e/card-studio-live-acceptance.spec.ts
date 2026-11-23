import { randomUUID } from "node:crypto";
import type { Page, Request, TestInfo } from "@playwright/test";
import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * KGUI-CARD-STUDIO-01E: real, authenticated Chromium acceptance.
 *
 * Opt-in only. The approved host must run the real backend with Card Studio
 * enabled and an authorized sanitized account. Never intercept a success
 * response, synthesize a committed card, install a test auth bypass, or
 * silently treat an unavailable endpoint as an empty template library.
 * For the response-loss trial, route.fetch() actually commits on the server
 * before Playwright drops the browser-facing response exactly once.
 */
const enabled = process.env.KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE === "true";
const mutationApproved = process.env.KAREN_CARD_STUDIO_MUTATION_APPROVED === "true";
const capture = process.env.KAREN_CARD_STUDIO_SANITIZED_CAPTURE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const isolationEmail = process.env.KAREN_UX_ISOLATION_EMAIL;
const isolationPassword = process.env.KAREN_UX_ISOLATION_PASSWORD;
const localLoopback = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";

/**
 * The shared protected settings/browser workflow sets this admission bit
 * before invoking the dedicated Card Studio spec. Playwright returns exit 0
 * when all opt-in tests are skipped, so a protected run must reject a missing
 * opt-in or incomplete two-principal mutation authorization at module load.
 *
 * Ordinary developer test discovery still skips this opt-in suite and never
 * requires real credentials. This check does not authorize any mutation.
 */
if (process.env.KAREN_SETTINGS_VERIFIED_DEPLOYMENT === "true" &&
    (!enabled || !mutationApproved || !email || !password ||
     !isolationEmail || !isolationPassword)) {
  throw new Error(
    "Protected Card Studio browser acceptance needs the enabled suite, " +
    "explicit disposable mutation approval, and two sanitized identities. " +
    "Skipped acceptance cannot certify consumer readiness.",
  );
}
const catalogPath = "/api/chat/card-studio/catalog";
const templatesPath = "/api/chat/card-studio/templates";
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

test.use({ trace: "off", screenshot: "off", video: "off", colorScheme: "dark" });

function approvedOrigin(): URL {
  const raw = process.env.KAREN_BASE_URL;
  if (!raw) throw new Error("An approved KAREN_BASE_URL is required.");
  const url = new URL(raw);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Browser credentials require an undecorated origin.");
  }
  const isLocal = localLoopback && url.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(url.hostname) && Boolean(url.port);
  const isHttps = url.protocol === "https:" && !url.port;
  if (!isLocal && !isHttps) {
    throw new Error("Only approved HTTPS or explicitly opted-in local loopback is allowed.");
  }
  if (capture && process.env.KAREN_SANITIZED_ACCOUNT !== "true") {
    throw new Error("Sanitized screenshot capture requires explicit identity approval.");
  }
  return url;
}

function isApi(request: Request, origin: string, path: string, method: string): boolean {
  const url = new URL(request.url());
  return url.origin === origin && url.pathname === path && request.method() === method;
}

async function realResponse(
  page: Page, origin: string, path: string, method: string,
) {
  return page.waitForResponse(
    response => isApi(response.request(), origin, path, method),
    { timeout: 45_000 },
  );
}

async function signIn(page: Page): Promise<URL> {
  if (!email || !password) {
    throw new Error("Dedicated sanitized login credentials were not supplied.");
  }
  const origin = approvedOrigin();
  await signInApprovedKaren(page, email, password, { allowLocalLoopback: localLoopback });
  expect(new URL(page.url()).origin).toBe(origin.origin);
  return origin;
}

async function openStudio(page: Page, origin: string) {
  const catalog = realResponse(page, origin, catalogPath, "GET");
  const library = realResponse(page, origin, templatesPath, "GET");

  let advanced = page.getByTestId("advanced-tools-toggle");
  if (!(await advanced.isVisible().catch(() => false))) {
    const sidebar = page.locator('[data-sidebar="trigger"]').first();
    await expect(sidebar).toBeVisible();
    await sidebar.click();
    advanced = page.getByTestId("advanced-tools-toggle");
  }
  await expect(advanced).toBeVisible();
  if (await advanced.getAttribute("aria-expanded") !== "true") {
    await advanced.click();
  }
  const navigation = page.getByRole("button", { name: "Card Studio", exact: true });
  await expect(navigation).toBeVisible();
  await navigation.click();

  const [catalogResponse, libraryResponse] = await Promise.all([catalog, library]);
  expect(catalogResponse.status(), "Catalog requires real HTTP 200 authorization").toBe(200);
  expect(libraryResponse.status(), "Library requires real HTTP 200 authorization").toBe(200);
  const hostCatalog: unknown = await catalogResponse.json();
  const saved: unknown = await libraryResponse.json();
  if (!hostCatalog || typeof hostCatalog !== "object" ||
      (hostCatalog as Record<string, unknown>).schema_version !== 1 ||
      !Array.isArray((hostCatalog as Record<string, unknown>).catalog) ||
      ((hostCatalog as Record<string, unknown>).catalog as unknown[]).length === 0) {
    throw new Error("Real host catalog is invalid or empty.");
  }
  if (!saved || typeof saved !== "object" ||
      (saved as Record<string, unknown>).schema_version !== 1 ||
      !Array.isArray((saved as Record<string, unknown>).templates)) {
    throw new Error("Real owned Card Studio inventory is invalid.");
  }
  const root = page.getByTestId("card-studio-workspace");
  await expect(root).toBeVisible();
  await expect(root.getByRole("heading", { name: "Card Studio" })).toBeVisible();
  await expect(root.getByTestId("card-studio-preview")).toBeVisible();
  return root;
}

async function checkGeometry(page: Page, root: ReturnType<Page["getByTestId"]>) {
  await expect.poll(async () => root.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const viewport = document.documentElement.clientWidth;
    return rect.width > 0 && rect.left >= -1 && rect.right <= viewport + 1 &&
      document.documentElement.scrollWidth <= viewport + 1;
  }), {
    timeout: 10_000,
    message: "Card Studio workspace must fit the actual browser viewport.",
  }).toBe(true);

  const columns = root.getByRole("region", { name: "Inert layout preview" });
  await expect(columns).toBeVisible();
  await expect(root.getByRole("region", { name: "Layout editor" })).toBeVisible();
  await expect(root.getByRole("complementary", { name: "Saved card layouts" })).toBeVisible();
  // Responsive adaptation is measured by the real DOM, not screenshot-size
  // manipulation or an unstated visual diff tolerance.
  const preview = await root.getByTestId("card-studio-preview").boundingBox();
  expect(preview?.width).toBeGreaterThan(0);
}

type Commit = {
  schema_version: number;
  committed: boolean;
  template: {
    template_id: string;
    template_key: string;
    revision: number;
    lifecycle: string;
    definition: { title: string; template_key: string };
  };
  receipt: {
    operation: string;
    idempotency_key: string;
    template_id: string;
    revision: number;
  };
};

async function verifiedCommit(
  page: Page, origin: string, path: string, method: string,
  click: () => Promise<void>, operation: string,
): Promise<{ saved: Commit; request: Record<string, unknown> }> {
  const pending = realResponse(page, origin, path, method);
  await click();
  const response = await pending;
  expect(response.status(), `${operation} must return real committed HTTP 200`).toBe(200);
  const result = await response.json() as Commit;
  expect(result.schema_version).toBe(1);
  expect(result.committed).toBe(true);
  expect(result.receipt.operation).toBe(operation);
  expect(result.receipt.template_id).toBe(result.template.template_id);
  expect(result.receipt.revision).toBe(result.template.revision);
  const request = response.request().postDataJSON() as Record<string, unknown>;
  expect(result.receipt.idempotency_key).toBe(request.idempotency_key);
  expect(request).not.toHaveProperty("tenant_id");
  expect(request).not.toHaveProperty("user_id");
  return { saved: result, request };
}

async function archiveOwned(
  page: Page, origin: string, templateId: string, expectedRevision: number,
) {
  page.once("dialog", dialog => void dialog.accept());
  const { saved, request } = await verifiedCommit(
    page, origin, `${templatesPath}/${templateId}/archive`, "POST",
    () => page.getByTestId("card-studio-workspace")
      .getByRole("button", { name: "Archive", exact: true }).click(),
    "archive",
  );
  expect(request.expected_revision).toBe(expectedRevision);
  expect(saved.template.revision).toBe(expectedRevision);
  expect(saved.template.lifecycle).toBe("archived");
  await expect(page.getByTestId("card-studio-workspace")
    .getByText(`Revision ${expectedRevision} · archived`)).toBeVisible();
}

test("KCARD-LIVE: real owner catalog, four viewports, keyboard and inert geometry", async (
  { page }, info: TestInfo,
) => {
  test.skip(!enabled, "Opt in to approved real Card Studio browser acceptance.");
  test.setTimeout(5 * 60_000);
  await page.setViewportSize(viewports[0]);
  const origin = await signIn(page);
  const root = await openStudio(page, origin.origin);
  await expect(root.getByText("Not connected to runtime evidence")).toBeVisible();
  await expect(root.getByText(/Draft only · Read-only components/)).toBeVisible();

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await checkGeometry(page, root);
    await expect(root.getByRole("button", { name: "Add slot" })).toBeEnabled();
    if (capture) {
      await info.attach(`card-studio-sanitized-${viewport.width}x${viewport.height}`, {
        body: await root.screenshot({ animations: "disabled" }),
        contentType: "image/png",
      });
    }
  }

  // Actual Tab traversal, not an element.focus() call, proves keyboard reach.
  await page.setViewportSize(viewports[0]);
  const addSlot = root.getByRole("button", { name: "Add slot" });
  await root.getByRole("heading", { name: "Template definition" }).click();
  let reached = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await page.keyboard.press("Tab");
    if (await addSlot.evaluate(element => element === document.activeElement)) {
      reached = true;
      break;
    }
  }
  expect(reached, "Add slot must be keyboard reachable").toBe(true);
  await addSlot.press("Enter");
  await expect(root.getByText("Not connected to runtime evidence")).toHaveCount(2);
  const down = root.getByRole("button", { name: "Move primary down" });
  await down.press("Enter");
  await expect(root.getByTestId("card-studio-preview").locator("article").first())
    .toContainText("slot_1");
  expect((await root.getByTestId("card-studio-preview").textContent()) ?? "")
    .not.toMatch(/localhost|<script|javascript:/i);
});

test("KCARD-LIVE-MUTATION: real PostgreSQL CAS, reload, response loss and archive", async (
  { page, context },
) => {
  test.skip(!enabled, "Opt in to approved real Card Studio browser acceptance.");
  test.setTimeout(9 * 60_000);
  if (!mutationApproved) {
    throw new Error("Explicit disposable mutation approval is required.");
  }
  const origin = await signIn(page);
  const root = await openStudio(page, origin.origin);
  const sample = randomUUID().replaceAll("-", "").slice(0, 16);
  const key = `card-e2e-${sample}`;
  const title = `Card E2E ${sample}`;
  const revisionTitle = `Card E2E revision ${sample}`;

  await root.getByLabel("Title", { exact: true }).fill(title);
  await root.getByLabel("Template key").fill(key);
  const created = await verifiedCommit(
    page, origin.origin, templatesPath, "POST",
    () => root.getByRole("button", { name: "Create draft" }).click(),
    "create",
  );
  const id = created.saved.template.template_id;
  expect(created.saved.template.revision).toBe(1);
  expect(created.saved.template.template_key).toBe(key);
  await expect(root.getByText("Saved revision 1 with a verified server receipt.")).toBeVisible();

  // A genuine reload must fetch the server's owned library again.
  await page.reload();
  const afterReload = await openStudio(page, origin.origin);
  const savedEntry = afterReload.getByRole("button", { name: new RegExp(title) });
  await expect(savedEntry).toBeVisible();
  await savedEntry.click();
  await expect(afterReload.getByLabel("Title", { exact: true })).toHaveValue(title);
  await expect(afterReload.getByText("Server revision 1")).toBeVisible();

  // A second real tab shares the authenticated account but holds a stale
  // revision. Both operations hit the same actual owner-scoped backend.
  const second = await context.newPage();
  try {
    await second.goto(new URL("/dashboard", origin).toString());
    const other = await openStudio(second, origin.origin);
    await other.getByRole("button", { name: new RegExp(title) }).click();
    await expect(other.getByText("Server revision 1")).toBeVisible();

    await afterReload.getByLabel("Title", { exact: true }).fill(revisionTitle);
    const updated = await verifiedCommit(
      page, origin.origin, `${templatesPath}/${id}`, "PUT",
      () => afterReload.getByRole("button", { name: "Save revision" }).click(),
      "revise",
    );
    expect(updated.request.expected_revision).toBe(1);
    expect(updated.saved.template.revision).toBe(2);
    await expect(afterReload.getByText("Saved revision 2 with a verified server receipt.")).toBeVisible();

    await other.getByLabel("Title", { exact: true }).fill(`Stale edit ${sample}`);
    const conflictWait = realResponse(second, origin.origin, `${templatesPath}/${id}`, "PUT");
    await other.getByRole("button", { name: "Save revision" }).click();
    const conflict = await conflictWait;
    expect(conflict.status(), "Stale tab must receive actual backend CAS 409").toBe(409);
    await expect(other.getByRole("alert")).toContainText("concurrent revision");
    await expect(other.getByLabel("Title", { exact: true })).toHaveValue(`Stale edit ${sample}`);
    await expect(other.getByText(/Saved revision 3/)).toHaveCount(0);

    second.once("dialog", dialog => void dialog.accept());
    const nextRead = realResponse(second, origin.origin, templatesPath, "GET");
    await other.getByRole("button", { name: "Reload" }).click();
    expect((await nextRead).status()).toBe(200);
    await other.getByRole("button", { name: new RegExp(revisionTitle) }).click();
    await expect(other.getByLabel("Title", { exact: true })).toHaveValue(revisionTitle);
    await expect(other.getByText("Server revision 2")).toBeVisible();
  } finally {
    await second.close();
  }
  await archiveOwned(page, origin.origin, id, 2);

  // Deliberately lose the browser response after a genuine server commit.
  // The frontend must not send a new request automatically, nor claim success.
  await afterReload.getByRole("button", { name: "New layout" }).click();
  const recoveryKey = `retry-e2e-${sample}`;
  const recoveryTitle = `Recovery E2E ${sample}`;
  await afterReload.getByLabel("Title", { exact: true }).fill(recoveryTitle);
  await afterReload.getByLabel("Template key").fill(recoveryKey);

  let firstBackendCommit: Commit | null = null;
  let lostRequest: Record<string, unknown> | null = null;
  let actualPosts = 0;
  let intercepted = false;
  await page.route("**/api/chat/card-studio/templates", async route => {
    if (!isApi(route.request(), origin.origin, templatesPath, "POST")) {
      await route.continue();
      return;
    }
    actualPosts += 1;
    if (!intercepted) {
      intercepted = true;
      lostRequest = route.request().postDataJSON() as Record<string, unknown>;
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.status(), "Actual backend must first accept the mutation").toBe(200);
      firstBackendCommit = await response.json() as Commit;
      expect(firstBackendCommit.committed).toBe(true);
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await afterReload.getByRole("button", { name: "Create draft" }).click();
  await expect(afterReload.getByText("Unverified save outcome")).toBeVisible();
  await expect(afterReload.getByRole("button", { name: "Retry identical request" })).toBeEnabled();
  expect(actualPosts).toBe(1);
  await expect(afterReload.getByText("Saved revision 1 with a verified server receipt.")).toHaveCount(0);

  // Recovery survives real tab navigation and reuses the original immutable
  // sessionStorage request. It never recovers by minting another UUID.
  await page.reload();
  const recovered = await openStudio(page, origin.origin);
  await expect(recovered.getByText("Unverified save outcome")).toBeVisible();
  const replay = await verifiedCommit(
    page, origin.origin, templatesPath, "POST",
    () => recovered.getByRole("button", { name: "Retry identical request" }).click(),
    "create",
  );
  expect(actualPosts).toBe(2);
  expect(replay.request).toEqual(lostRequest);
  expect(replay.saved.template.template_id)
    .toBe((firstBackendCommit as Commit | null)?.template.template_id);
  expect(replay.saved.template.revision).toBe(1);
  await expect(recovered.getByText("Saved revision 1 with a verified server receipt.")).toBeVisible();
  await page.unroute("**/api/chat/card-studio/templates");
  await archiveOwned(page, origin.origin, replay.saved.template.template_id, 1);

  // Archived records must survive reload and remain server-owned.
  await page.reload();
  const finalPage = await openStudio(page, origin.origin);
  await expect(finalPage.getByRole("button", { name: new RegExp(revisionTitle) }))
    .toContainText("archived");
  await expect(finalPage.getByRole("button", { name: new RegExp(recoveryTitle) }))
    .toContainText("archived");
});


/**
 * An actual second first-party identity, never a forged access token, must
 * fail all foreign-owner reads and writes. The two browser contexts share at
 * most the reviewed Vercel protection cookie, not Karen authentication state.
 */
async function scopedCardRequest(
  page: Page,
  path: string,
  method: "GET" | "PUT" | "POST",
  body?: Record<string, unknown>,
): Promise<{ status: number; cacheControl: string | null; payload: unknown }> {
  return page.evaluate(async ({ path, method, body }) => {
    const bearer = window.localStorage.getItem("access_token");
    if (!bearer) {
      throw new Error("Authenticated browser did not establish a bearer token.");
    }
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin ||
        !url.pathname.startsWith("/api/chat/card-studio/")) {
      throw new Error("Refusing cross-origin Card Studio authorization probe.");
    }
    const response = await window.fetch(url.toString(), {
      method,
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      headers: {
        Authorization: "Bearer " + bearer,
        ...(method === "GET" ? {} : { "Content-Type": "application/json" }),
      },
      ...(method === "GET" ? {} : { body: JSON.stringify(body) }),
    });
    return {
      status: response.status,
      cacheControl: response.headers.get("cache-control"),
      payload: response.ok ? await response.json() as unknown : null,
    };
  }, { path, method, body });
}

test("KCARD-LIVE-ISOLATION: second real user cannot read, revise or archive owner layouts", async (
  { page, browser },
) => {
  test.skip(!enabled, "Opt in to approved real Card Studio browser acceptance.");
  test.setTimeout(7 * 60_000);
  if (!mutationApproved) {
    throw new Error("Real owner isolation requires explicitly approved disposable preview writes.");
  }
  if (!email || !password || !isolationEmail || !isolationPassword ||
      email.trim().toLowerCase() === isolationEmail.trim().toLowerCase()) {
    throw new Error("Two distinct sanitized Card Studio accounts are required.");
  }

  const origin = await signIn(page);
  const ownerUserId = await page.evaluate(() => {
    const user = JSON.parse(window.localStorage.getItem("user_data") || "null") as { user_id?: unknown } | null;
    if (typeof user?.user_id !== "string" || !user.user_id) throw new Error("Owner login did not resolve a user ID.");
    return user.user_id;
  });
  const root = await openStudio(page, origin.origin);
  const sample = randomUUID().replaceAll("-", "").slice(0, 16);
  const key = "isolation-e2e-" + sample;
  const title = "Card Isolation E2E " + sample;
  await root.getByLabel("Title", { exact: true }).fill(title);
  await root.getByLabel("Template key").fill(key);
  const created = await verifiedCommit(
    page, origin.origin, templatesPath, "POST",
    () => root.getByRole("button", { name: "Create draft" }).click(),
    "create",
  );
  const ownerId = created.saved.template.template_id;
  expect(created.saved.template.revision).toBe(1);
  expect(created.saved.template.lifecycle).toBe("draft");

  try {
    const otherContext = await browser.newContext({
      baseURL: origin.origin,
      serviceWorkers: "block",
      viewport: { width: 1280, height: 800 },
    });
    try {
      // Pass only immutable-host Vercel deployment access. Never inherit the
      // owner application's kari_session, bearer, localStorage or user data.
      const accessCookies = (await page.context().cookies(origin.origin))
        .filter(cookie => cookie.name === "_vercel_jwt" && cookie.secure &&
          cookie.domain.replace(/^\./, "") === origin.hostname);
      if (origin.hostname.endsWith(".vercel.app") && accessCookies.length !== 1) {
        throw new Error("Second browser lacks approved protected-preview admission.");
      }
      if (accessCookies.length > 0) {
        await otherContext.addCookies(accessCookies);
      }

      const other = await otherContext.newPage();
      await signInApprovedKaren(other, isolationEmail, isolationPassword, {
        allowLocalLoopback: localLoopback,
      });
      expect(new URL(other.url()).origin).toBe(origin.origin);
      const foreignUserId = await other.evaluate(() => {
        const user = JSON.parse(window.localStorage.getItem("user_data") || "null") as { user_id?: unknown } | null;
        if (typeof user?.user_id !== "string" || !user.user_id) throw new Error("Second login did not resolve a user ID.");
        return user.user_id;
      });
      expect(foreignUserId !== ownerUserId, "Isolation requires distinct authenticated users").toBe(true);
      const foreignRoot = await openStudio(other, origin.origin);
      await expect(foreignRoot.getByRole("button", { name: new RegExp(title) }))
        .toHaveCount(0);

      // Explicitly prove B has their own write capability. An ordinary RBAC
      // 403 for a read-only account would be weak cross-owner isolation proof.
      const foreignKey = "isolation-foreign-e2e-" + sample;
      const foreignTitle = "Foreign isolation E2E " + sample;
      await foreignRoot.getByLabel("Title", { exact: true }).fill(foreignTitle);
      await foreignRoot.getByLabel("Template key").fill(foreignKey);
      const foreignCreated = await verifiedCommit(
        other, origin.origin, templatesPath, "POST",
        () => foreignRoot.getByRole("button", { name: "Create draft" }).click(),
        "create",
      );
      const foreignId = foreignCreated.saved.template.template_id;
      expect(foreignCreated.saved.template.revision).toBe(1);
      expect(foreignCreated.saved.template.lifecycle).toBe("draft");
      try {
        // B also has functional authenticated read admission. A disabled
        // plugin, missing bearer or missing write permission cannot count.
        const foreignInventory = await scopedCardRequest(
          other, templatesPath + "?limit=50&include_archived=true", "GET",
        );
        expect(foreignInventory.status).toBe(200);
        expect(foreignInventory.cacheControl).toContain("no-store");
        const owned = foreignInventory.payload as {
          schema_version: number;
          templates: Array<{ template_id: string; template_key: string }>;
        };
        expect(owned.schema_version).toBe(1);
        expect(Array.isArray(owned.templates)).toBe(true);
        expect(owned.templates.some(item => item.template_id === foreignId)).toBe(true);
        expect(owned.templates.some(item =>
          item.template_id === ownerId || item.template_key === key)).toBe(false);

        // Read current source, historical list, historical source, and both
        // write paths. 403/404 are allowable denials; 401 is not, since this
        // account just demonstrated independent authenticated read admission.
        const draft = created.request.draft as Record<string, unknown>;
        const foreignProbes: Array<{
          path: string;
          method: "GET" | "PUT" | "POST";
          body?: Record<string, unknown>;
        }> = [
          { path: templatesPath + "/" + ownerId, method: "GET" },
          { path: templatesPath + "/" + ownerId + "/revisions", method: "GET" },
          { path: templatesPath + "/" + ownerId + "/revisions/1", method: "GET" },
          {
            path: templatesPath + "/" + ownerId, method: "PUT",
            body: {
              idempotency_key: randomUUID(),
              expected_revision: 1,
              draft: { ...draft, title: "Illicit revision " + sample },
            },
          },
          {
            path: templatesPath + "/" + ownerId + "/archive", method: "POST",
            body: { idempotency_key: randomUUID(), expected_revision: 1 },
          },
        ];
        for (const probe of foreignProbes) {
          const result = await scopedCardRequest(other, probe.path, probe.method, probe.body);
          expect([403, 404], "Foreign " + probe.method + " " + probe.path + " must be denied")
            .toContain(result.status);
          expect(result.cacheControl).toContain("no-store");
        }

        // Denials must leave the actual owner's persisted PostgreSQL revision
        // unchanged. This read is independently authorized in the owner tab.
        const ownerRead = await scopedCardRequest(page, templatesPath + "/" + ownerId, "GET");
        expect(ownerRead.status).toBe(200);
        expect(ownerRead.cacheControl).toContain("no-store");
        const ownerTemplate = ownerRead.payload as {
          schema_version: number;
          template: {
            template_id: string; revision: number; lifecycle: string;
            definition: { title: string; template_key: string };
          };
        };
        expect(ownerTemplate.schema_version).toBe(1);
        expect(ownerTemplate.template.template_id).toBe(ownerId);
        expect(ownerTemplate.template.revision).toBe(1);
        expect(ownerTemplate.template.lifecycle).toBe("draft");
        expect(ownerTemplate.template.definition.title).toBe(title);
        expect(ownerTemplate.template.definition.template_key).toBe(key);
      } finally {
        await archiveOwned(other, origin.origin, foreignId, 1);
      }
    } finally {
      await otherContext.close();
    }
  } finally {
    // Even a failed negative-auth trial attempts to archive its own fixture.
    // A failed cleanup fails the trial rather than falsely claiming no data.
    await archiveOwned(page, origin.origin, ownerId, 1);
  }
});
