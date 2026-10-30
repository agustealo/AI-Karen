import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

// Mutates only a dedicated, operator-approved sanitized test account.
// No mock API receipts, inference calls, screenshots, videos or storage-state exports.
test.use({ trace: "off", screenshot: "off", video: "off" });
test.setTimeout(120000);

const required = process.env.KAREN_PERSONA_HANDOFF_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SavedPreferences = {
  revision: number;
  active_persona_id: string | null;
  show_persona_selector: boolean;
};

function assertPreference(value: SavedPreferences) {
  expect(Number.isSafeInteger(value.revision)).toBe(true);
  expect(value.show_persona_selector).toBe(true);
}

test("persona switch offers a real new conversation without hidden inference", async ({ page }) => {
  test.skip(!required, "Only run with explicit sanitized-principal mutation approval");
  if (!email || !password) {
    throw new Error("Approved persona handoff requires sanitized credentials");
  }
  await signInApprovedKaren(page, email, password);
  await expect(page.getByTestId("karen-assistant-ui-chat")).toBeVisible({ timeout: 30000 });

  const preferencesUrl = "/api/personas/preferences/me";
  const beforeResponse = await page.request.get(preferencesUrl);
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json() as SavedPreferences;
  assertPreference(before);
  const catalogResponse = await page.request.get("/api/personas/");
  expect(catalogResponse.status()).toBe(200);
  const catalog = await catalogResponse.json() as Array<{
    id: string; name: string; is_active: boolean;
  }>;
  expect(Array.isArray(catalog)).toBe(true);
  const alternative = catalog.find(p =>
    p && p.is_active === true && typeof p.id === "string" &&
    p.id.length > 0 && p.id !== before.active_persona_id
  );
  expect(alternative, "Sanitized account needs a second active persona").toBeDefined();
  if (!alternative) return;

  const inferenceRequests: string[] = [];
  page.context().on("request", request => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (path === "/api/chat" || path === "/api/chat/stream" ||
        path === "/api/chat/ag-ui" ||
        path === "/api/copilotkit/agent/default/run") {
      inferenceRequests.push(path);
    }
  });

  let createdConversationId: string | null = null;
  try {
    const selector = page.getByRole("combobox", { name: "Active Karen persona" });
    await expect(selector).toHaveValue(before.active_persona_id ?? "");

    const confirmedSave = page.waitForResponse(response =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname === preferencesUrl,
      { timeout: 20000 }
    );
    await selector.selectOption(alternative.id);
    const savedResponse = await confirmedSave;
    expect(savedResponse.status()).toBe(200);
    const saved = await savedResponse.json() as SavedPreferences;
    expect(saved.revision).toBe(before.revision + 1);
    expect(saved.active_persona_id).toBe(alternative.id);
    await expect(selector).toHaveValue(alternative.id);

    const start = page.getByRole("button", {
      name: "Start new conversation for selected persona",
    });
    await expect(start).toBeVisible();
    await expect(page.getByText(
      "Persona selection saved. To keep conversations separate, start a new thread before sending.",
    )).toBeVisible();
    expect(inferenceRequests, "Changing persona must not run a model").toEqual([]);

    const created = page.waitForResponse(response =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.startsWith("/api/conversations/ensure-session/"),
      { timeout: 20000 }
    );
    await start.click();
    const createdResponse = await created;
    expect(createdResponse.status()).toBe(200);
    const receipt = await createdResponse.json() as { id: string; messages?: unknown[] };
    expect(UUID.test(receipt.id)).toBe(true);
    createdConversationId = receipt.id;
    await expect(start).toHaveCount(0);

    const owned = await page.request.get(
      "/api/conversations/" + encodeURIComponent(createdConversationId),
    );
    expect(owned.status(), "New thread must be readable from Karen's owner-scoped API").toBe(200);
    const conversation = await owned.json() as { id: string; messages?: unknown[] };
    expect(conversation.id).toBe(createdConversationId);
    expect(conversation.messages ?? []).toEqual([]);
    expect(inferenceRequests, "New-thread creation must not run a model").toEqual([]);
  } finally {
    // Never clobber a newer change in another tab. Restore only the exact
    // test-owned selection using the latest backend revision.
    const nowResponse = await page.request.get(preferencesUrl);
    expect(nowResponse.status()).toBe(200);
    const now = await nowResponse.json() as SavedPreferences;
    expect(now.active_persona_id, "Do not overwrite a concurrent persona switch")
      .toBe(alternative.id);
    const restoredResponse = await page.request.put(preferencesUrl, {
      data: {
        active_persona_id: before.active_persona_id,
        expected_revision: now.revision,
      },
    });
    expect(restoredResponse.status()).toBe(200);
    const restored = await restoredResponse.json() as SavedPreferences;
    expect(restored.active_persona_id).toBe(before.active_persona_id);
    expect(restored.revision).toBe(now.revision + 1);

    if (createdConversationId) {
      const existing = await page.request.get(
        "/api/conversations/" + encodeURIComponent(createdConversationId),
      );
      expect(existing.status()).toBe(200);
      const value = await existing.json() as { messages?: unknown[] };
      expect(value.messages ?? [], "Never delete a conversation receiving real content")
        .toEqual([]);
      const deleted = await page.request.delete(
        "/api/conversations/" + encodeURIComponent(createdConversationId),
      );
      expect([200, 204]).toContain(deleted.status());
    }
  }
});
