import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

// This visits a REAL isolated candidate on a sanitized reviewed deployment.
// No mocking, model execution, password recording or browser-state uploads.
test.use({ trace: "off", screenshot: "off", video: "off" });

const required = process.env.KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const conversationId = process.env.KAREN_HISTORY_CONVERSATION_ID;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const text = "CK-07E8 approved unsent draft verification";

function requireApprovedNativeFixture() {
  if (required && (!email || !password || !conversationId || !UUID.test(conversationId))) {
    throw new Error("Native CopilotKit proof requires approved credentials and owned conversation UUID");
  }
  test.skip(!email || !password || !conversationId || !UUID.test(conversationId),
    "Only runs with explicit approved sanitized browser fixtures");
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

  // Current consumer route remains unchanged after visiting candidate.
  await page.goto("/dashboard");
  await expect(page.getByTestId("karen-assistant-ui-chat")).toBeVisible();
});
