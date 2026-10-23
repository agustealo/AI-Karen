import { expect, test } from "@playwright/test";

// This test enters real credentials and reads persisted user content.
// Never record its browser state, regardless of the runner configuration.
test.use({ trace: "off", screenshot: "off", video: "off" });

/**
 * Opt-in, live authenticated acceptance against a sanitized deployment.
 * Reads an existing canonical conversation. Never intercepts APIs, fabricates
 * persistence, creates synthetic assistant messages, or records credentials.
 */
const required = process.env.KAREN_HISTORY_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const conversationId = process.env.KAREN_HISTORY_CONVERSATION_ID;

test("reopening an owned conversation preserves its saved answer and execution receipt", async ({ page }) => {
  // Verify the actual rendered assistant-ui, not a runner-side build flag.
  // A legacy-only deployment fails at the chat visibility assertion below.
  if (required && (!email || !password || !conversationId)) {
    throw new Error("Live history acceptance requires credentials and KAREN_HISTORY_CONVERSATION_ID");
  }
  test.skip(!email || !password || !conversationId, "Requires an approved sanitized conversation fixture");
  if (!email || !password || !conversationId) return;

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/dashboard(?:[/?#]|$)"), { timeout: 30_000 });

  const response = await page.request.get(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
  );
  expect(response.ok(), "The authenticated API must authorize the exact conversation").toBe(true);
  const stored = await response.json() as {
    id: string;
    title?: string;
    messages?: Array<{ role: string; content: string; metadata?: Record<string, unknown>; structured_content?: { presentation?: { component_type?: string } } }>;
  };
  expect(stored.id).toBe(conversationId);
  expect(Array.isArray(stored.messages)).toBe(true);
  const assistant = stored.messages?.find(message =>
    message.role === "assistant" &&
    typeof message.metadata?.actual_provider === "string" &&
    message.metadata.actual_provider.trim().length > 0 &&
    typeof message.metadata?.actual_model === "string" &&
    message.metadata.actual_model.trim().length > 0 &&
    typeof message.metadata?.response_source === "string" &&
    message.metadata.response_source.trim().length > 0 &&
    typeof message.structured_content?.presentation?.component_type === "string",
  );
  expect(assistant, "Fixture must include an actual persisted execution receipt").toBeDefined();
  if (!assistant) return;
  const surface = assistant.structured_content?.presentation as
    | { component_type?: string; data?: { layout?: string; items?: Array<{ component_type?: string; presentation_id?: string; evidence_ref?: string }>; evidence_refs?: string[] } }
    | undefined;
  const kind = surface?.component_type;
  const layoutReceipt = assistant.metadata?.presentation_layout_provenance as
    | { provider?: string; model?: string; response_source?: string; part_ids?: string[] }
    | undefined;
  if (kind === "surface.composition" && layoutReceipt) {
    expect(layoutReceipt.provider?.trim()).toBeTruthy();
    expect(layoutReceipt.model?.trim()).toBeTruthy();
    expect(layoutReceipt.response_source).toBe("surface_layout_model");
    expect(layoutReceipt.part_ids).toEqual(
      surface?.data?.items?.map(item => item.presentation_id),
    );
  }
  if (kind === "surface.composition") {
    const parts = surface?.data?.items || [];
    expect(["stack", "grid"]).toContain(surface?.data?.layout);
    expect(parts.length).toBeGreaterThan(0);
    expect(new Set(parts.map(part => part.presentation_id)).size).toBe(parts.length);
    expect(parts.every(part => typeof part.evidence_ref === "string" && !!part.evidence_ref)).toBe(true);
    if (surface?.data?.evidence_refs) {
      expect(new Set(surface.data.evidence_refs)).toEqual(new Set(parts.map(part => part.evidence_ref)));
    }
  }
  const presentationTestId: Record<string, string> = {
    "planner.task_list": "karen-planner-task-list",
    "weather.observation": "karen-weather-presentation",
    "weather.comparison": "karen-weather-comparison",
    "time.observation": "karen-time-presentation",
    "surface.composition": "karen-composed-surface",
  };
  expect(kind && presentationTestId[kind],
    "Acceptance fixture must contain a persisted allowlisted presentation").toBeTruthy();
  if (!kind || !presentationTestId[kind]) return;

  const chat = page.getByTestId("karen-assistant-ui-chat");
  await expect(chat).toBeVisible({ timeout: 30_000 });
  await chat.getByRole("button", { name: "Find conversations" }).click();
  await chat.getByPlaceholder("Search conversation titles").fill(stored.title || "");
  const ownedConversation = chat.locator('[data-conversation-id="' + conversationId + '"]');
  await expect(ownedConversation).toHaveCount(1);
  await ownedConversation.click();

  await expect(chat.getByText(assistant.content, { exact: true })).toBeVisible();
  const receipt = chat.getByTestId("karen-restored-execution-receipt");
  await expect(receipt.first()).toBeVisible();
  await expect(chat.getByTestId(presentationTestId[kind]).first()).toBeVisible();
  if (kind === "surface.composition") {
    const rendered = chat.getByTestId("karen-composed-surface").first();
    const childTestId: Record<string, string> = {
      "planner.task_list": "karen-planner-task-list",
      "weather.observation": "karen-weather-presentation",
      "weather.comparison": "karen-weather-comparison",
      "time.observation": "karen-time-presentation",
    };
    for (const item of surface?.data?.items || []) {
      expect(childTestId[item.component_type || ""]).toBeTruthy();
      await expect(rendered.getByTestId(childTestId[item.component_type || ""]).first()).toBeVisible();
    }
  }
  await receipt.first().locator("summary").click();
  await expect(receipt.first()).toContainText(String(assistant.metadata?.actual_model));
  await expect(receipt.first()).toContainText(String(assistant.metadata?.actual_provider));
  await expect(receipt.first()).toContainText(String(assistant.metadata?.response_source));

  // Reload verifies API-backed restoration, not only in-memory thread state.
  await page.reload();
  const reopened = page.getByTestId("karen-assistant-ui-chat");
  await expect(reopened).toBeVisible({ timeout: 30_000 });
  await reopened.getByRole("button", { name: "Find conversations" }).click();
  await reopened.getByPlaceholder("Search conversation titles").fill(stored.title || "");
  const reopenedOwnedConversation = reopened.locator('[data-conversation-id="' + conversationId + '"]');
  await expect(reopenedOwnedConversation).toHaveCount(1);
  await reopenedOwnedConversation.click();
  await expect(reopened.getByText(assistant.content, { exact: true }))
    .toBeVisible({ timeout: 30_000 });
  const restoredReceipt = reopened.getByTestId("karen-restored-execution-receipt").first();
  await expect(restoredReceipt).toBeVisible();
  await expect(reopened.getByTestId(presentationTestId[kind]).first()).toBeVisible();
  await restoredReceipt.locator("summary").click();
  await expect(restoredReceipt).toContainText(String(assistant.metadata?.actual_model));
  await expect(restoredReceipt).toContainText(String(assistant.metadata?.actual_provider));
  await expect(restoredReceipt).toContainText(String(assistant.metadata?.response_source));
});
