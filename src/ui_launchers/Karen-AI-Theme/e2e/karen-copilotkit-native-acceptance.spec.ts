import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { APIRequestContext } from "@playwright/test";

// This visits a REAL isolated candidate on a sanitized reviewed deployment.
// No mocking, model execution, password recording or browser-state uploads.
test.use({ trace: "off", screenshot: "off", video: "off" });

const required = process.env.KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const conversationId = process.env.KAREN_HISTORY_CONVERSATION_ID;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const text = "CK-07E8 approved unsent draft verification";
const elsewhere = "CK-07E8 verified other-tab CAS change";
const competing = "CK-07E8 local stale unsent text";
test.setTimeout(120000);

function requireApprovedNativeFixture() {
  if (required && (!email || !password || !conversationId || !UUID.test(conversationId))) {
    throw new Error("Native CopilotKit proof requires approved credentials and owned conversation UUID");
  }
  test.skip(!email || !password || !conversationId || !UUID.test(conversationId),
    "Only runs with explicit approved sanitized browser fixtures");
}


/** Clear only a draft value deliberately written by this sanitized suite.
 * Every cleanup uses the latest backend revision and refuses arbitrary edits.
 */
async function clearOnlyOwnAcceptanceDraft(
  request: APIRequestContext, url: string, ownValues: readonly string[],
) {
  const response = await request.get(url);
  expect(response.status(), "Cleanup must reread canonical draft").toBe(200);
  const current = await response.json() as { text: string; revision: number };
  expect(Number.isSafeInteger(current.revision)).toBe(true);
  if (!ownValues.includes(current.text)) return;
  const clear = await request.put(url, {
    data: { text: "", expected_revision: current.revision },
  });
  expect(clear.status(), "Sanitized draft cleanup must be CAS-confirmed").toBe(200);
  const receipt = await clear.json() as { text: string; revision: number };
  expect(receipt.text).toBe("");
  expect(receipt.revision).toBe(current.revision + 1);
}

test("CK-07E8 native controlled view retains an authenticated draft without starting inference", async ({ page }) => {
  requireApprovedNativeFixture();
  if (!email || !password || !conversationId) return;

  await signInApprovedKaren(page, email, password);
  const draftUrl = "/api/conversations/" + encodeURIComponent(conversationId) + "/draft";
  const initial = await page.request.get(draftUrl);
  expect(initial.status(), "Owned canonical draft must be reachable").toBe(200);
  const initialDraft = await initial.json() as { text: string; revision: number };
  expect(initialDraft.text, "Only a dedicated sanitized blank draft may be modified").toBe("");
  expect(Number.isSafeInteger(initialDraft.revision)).toBe(true);

  try {
    let runs = 0;
    page.on("request", request => {
      if (request.method() === "POST" &&
          new URL(request.url()).pathname === "/api/copilotkit/agent/default/run") {
        runs += 1;
      }
    });

    const css = await page.request.get("/vendor/copilotkit-v2.css");
    expect(css.status(), "Pinned native SDK stylesheet must be served locally").toBe(200);
    expect(css.headers()["content-type"]).toContain("text/css");
    await page.goto("/acceptance/copilotkit/" + encodeURIComponent(conversationId));
    const candidate = page.getByTestId("karen-copilot-controlled-chat");
    await expect(candidate).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("karen-copilot-persona-footer")).toBeVisible();
    await expect(page.getByTestId("karen-assistant-ui-chat")).toHaveCount(0);
    expect(runs, "Mount must never automatically start a model").toBe(0);

    const composer = candidate.locator("textarea").first();
    await expect(composer).toBeVisible();
    await composer.focus();
    await expect(composer).toBeFocused();
    await composer.fill(text);

    await expect.poll(async () => {
      const response = await page.request.get(draftUrl);
      expect(response.status()).toBe(200);
      const value = await response.json() as { text: string };
      return value.text;
    }, { timeout: 15000 }).toBe(text);
    expect(runs, "Typing and saving a draft must not start a model").toBe(0);

    await page.reload();
    const restored = page.getByTestId("karen-copilot-controlled-chat").locator("textarea").first();
    await expect(restored).toHaveValue(text, { timeout: 30000 });
    expect(runs, "Reload must restore history and draft without inference").toBe(0);

    // Leave no acceptance artifact in the canonical draft store.
    await restored.fill("");
    await expect.poll(async () => {
      const response = await page.request.get(draftUrl);
      expect(response.status()).toBe(200);
      const value = await response.json() as { text: string };
      return value.text;
    }, { timeout: 15000 }).toBe("");
    expect(runs).toBe(0);

    // The same authenticated backend preference must govern the native footer.
    const personaResponse = await page.request.get("/api/personas/preferences/me");
    expect(personaResponse.status(), "Native persona preference must be backend-owned").toBe(200);
    const persona = await personaResponse.json() as {
      active_persona_id: string | null; show_persona_selector: boolean;
    };
    expect(typeof persona.show_persona_selector).toBe("boolean");
    const selector = page.getByRole("combobox", { name: "Active Karen persona" });
    if (persona.show_persona_selector) {
      await expect(selector).toBeVisible();
      await expect(selector).toHaveValue(persona.active_persona_id ?? "");
    } else {
      await expect(selector).toHaveCount(0);
    }

    // Responsive geometry is read-only and must not submit, reflow offscreen or
    // hide access to the shared native composer at a mobile viewport width.
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(restored).toBeVisible();
    await expect(page.getByTestId("karen-copilot-persona-footer")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
    expect(runs).toBe(0);

    // Current consumer route remains unchanged after visiting candidate.
    await page.goto("/dashboard");
    await expect(page.getByTestId("karen-assistant-ui-chat")).toBeVisible();
  } finally {
    await clearOnlyOwnAcceptanceDraft(page.request, draftUrl, [text]);
  }
});

test("CK-07E8 a stale second browser tab cannot overwrite an authenticated draft", async ({ page }) => {
  requireApprovedNativeFixture();
  if (!email || !password || !conversationId) return;
  await signInApprovedKaren(page, email, password);
  const draftUrl = "/api/conversations/" + encodeURIComponent(conversationId) + "/draft";
  const candidateUrl = "/acceptance/copilotkit/" + encodeURIComponent(conversationId);
  const initial = await page.request.get(draftUrl);
  expect(initial.status()).toBe(200);
  const base = await initial.json() as { text: string; revision: number };
  expect(base.text, "Use an isolated empty sanitized test draft").toBe("");
  expect(Number.isSafeInteger(base.revision)).toBe(true);

  let runs = 0;
  page.context().on("request", request => {
    if (request.method() === "POST" &&
        new URL(request.url()).pathname === "/api/copilotkit/agent/default/run") {
      runs += 1;
    }
  });
  await page.goto(candidateUrl);
  await expect(page.getByTestId("karen-copilot-controlled-chat")).toBeVisible();

  const tab = await page.context().newPage();
  try {
    await tab.goto(candidateUrl);
    const native = tab.getByTestId("karen-copilot-controlled-chat");
    await expect(native).toBeVisible();
    const composer = native.locator("textarea").first();
    await expect(composer).toHaveValue("");
    await tab.bringToFront();
    await composer.focus();
    await expect(composer).toBeFocused();

    // A real authenticated same-origin request from the FIRST browser tab
    // advances the canonical revision while the SECOND tab remains focused.
    // This guarantees the second tab's loaded revision is stale without mock
    // responses, artificial delays or an unauthorized forged server receipt.
    const otherTabWrite = await page.evaluate(async ({ url, value, revision }) => {
      const response = await fetch(url, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ text: value, expected_revision: revision }),
      });
      if (!response.ok) return { status: response.status, text: "", revision: -1 };
      const result = await response.json() as { text: string; revision: number };
      return { status: response.status, ...result };
    }, { url: draftUrl, value: elsewhere, revision: base.revision });
    expect(otherTabWrite).toEqual({
      status: 200, text: elsewhere, revision: base.revision + 1,
    });

    const rejectedStalePut = tab.waitForResponse(response =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname === draftUrl &&
      response.status() === 409,
      { timeout: 15000 },
    );
    await composer.fill(competing);
    await rejectedStalePut;
    await expect(tab.getByTestId("karen-copilot-unsynced-draft"))
      .toBeVisible({ timeout: 15000 });
    await expect(tab.getByRole("alert"))
      .toContainText("Draft changed in another window");
    await expect(tab.getByRole("textbox", { name: "Unsynced draft, copy before reload" }))
      .toHaveValue(competing);
    const saved = await page.request.get(draftUrl);
    expect(saved.status()).toBe(200);
    const savedValue = await saved.json() as { text: string; revision: number };
    expect(savedValue).toEqual({
      text: elsewhere, revision: base.revision + 1,
    });
    expect(runs, "Draft conflict cannot trigger an AI run").toBe(0);

    // Recovery must be an explicit user decision, with a fresh authenticated
    // read rather than silently overwriting the other tab's saved text.
    await tab.getByRole("button", {
      name: "Reload saved draft (discard local changes)",
    }).click();
    await expect(tab.getByTestId("karen-copilot-controlled-chat"))
      .toBeVisible({ timeout: 15000 });
    await expect(tab.getByTestId("karen-copilot-controlled-chat").locator("textarea").first())
      .toHaveValue(elsewhere);
    expect(runs).toBe(0);
  } finally {
    await tab.close();
    await clearOnlyOwnAcceptanceDraft(page.request, draftUrl, [elsewhere, competing]);
  }
});
