import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { APIRequestContext } from "@playwright/test";

// This visits a REAL isolated candidate on a sanitized reviewed deployment.
// Default scenarios never execute a model. One separately operator-approved
// test uses a disposable real model run and retained canonical audit evidence.
// No mocking, credential recording, traces, or browser-state uploads.
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
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;

// Explicitly include all known browser-side inference transports. A new
// bypass should fail the test, never be invisible to a single SDK path check.
function isInferenceRequest(url: string): boolean {
  const pathname = new URL(url).pathname;
  return pathname === "/api/copilotkit/agent/default/run" ||
    pathname === "/api/chat/ag-ui" ||
    pathname === "/api/chat/stream" ||
    pathname === "/api/chat";
}

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
    page.context().on("request", request => {
      if (request.method() === "POST" && isInferenceRequest(request.url())) {
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
    if (request.method() === "POST" && isInferenceRequest(request.url())) {
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

// A microphone-permission denial is a browser-level safety scenario, not a
// simulated transcript. Do not record or send any audio, start an LLM, or
// change a user's persona/draft state.
test("CK-07E8 denied local microphone permission never transcribes or starts an agent", async ({ page }) => {
  requireApprovedNativeFixture();
  if (!email || !password || !conversationId) return;
  await signInApprovedKaren(page, email, password);

  const capabilities = await page.request.get("/api/voice/capabilities");
  expect(capabilities.status(), "Voice capability must be reported by Karen's real backend").toBe(200);
  const voice: unknown = await capabilities.json();
  expect(voice && typeof voice === "object" && !Array.isArray(voice)).toBe(true);
  const advertised = voice as { status?: unknown; transcription_available?: unknown };
  expect(typeof advertised.status).toBe("string");
  expect(typeof advertised.transcription_available).toBe("boolean");

  // An intentionally disabled backend is not a voice parity success.
  test.skip(advertised.status !== "ready" || advertised.transcription_available !== true,
    "Local transcription is disabled on this approved deployment; permission proof remains unverified");

  const origin = new URL(process.env.KAREN_BASE_URL!).origin;
  await page.context().grantPermissions([], { origin });
  const forbidden: string[] = [];
  page.context().on("request", request => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (isInferenceRequest(request.url()) || path.startsWith("/api/voice/")) {
      forbidden.push(path);
    }
  });

  await page.goto("/acceptance/copilotkit/" + encodeURIComponent(conversationId));
  await expect(page.getByTestId("karen-copilot-controlled-chat")).toBeVisible();
  const controls = page.getByTestId("karen-copilot-voice-controls");
  await expect(controls).toBeVisible();
  const start = controls.getByRole("button", { name: "Start local dictation" });
  await expect(start).toBeEnabled();

  const draftUrl = "/api/conversations/" + encodeURIComponent(conversationId) + "/draft";
  const draftBefore = await page.request.get(draftUrl);
  expect(draftBefore.status()).toBe(200);
  const savedBefore = await draftBefore.json() as { text: string; revision: number };
  expect(typeof savedBefore.text).toBe("string");
  expect(Number.isSafeInteger(savedBefore.revision)).toBe(true);

  await start.click();
  await expect(controls.getByRole("alert"))
    .toContainText("Microphone access was denied or unavailable.");
  await expect(controls.getByRole("button", { name: "Start local dictation" }))
    .toHaveAttribute("aria-pressed", "false");
  expect(forbidden, "Permission denial must not submit audio or trigger a model").toEqual([]);

  const draftAfter = await page.request.get(draftUrl);
  expect(draftAfter.status()).toBe(200);
  expect(await draftAfter.json(), "Microphone denial must not modify the canonical draft")
    .toEqual(savedBefore);
});

/**
 * This is a deliberate mutation of the sanitized acceptance principal's own
 * persona preference, so it requires a separate explicit operator opt-in.
 * Never mutate a consumer's persona and never infer a model response here.
 */
test("CK-07E8 native persona selection persists a canonical revision and restores it", async ({ page }) => {
  requireApprovedNativeFixture();
  test.skip(process.env.KAREN_COPILOTKIT_PERSONA_MUTATION_REQUIRED !== "true",
    "Persona write acceptance requires explicit sanitized-principal approval");
  if (!email || !password || !conversationId) return;

  await signInApprovedKaren(page, email, password);
  const endpoint = "/api/personas/preferences/me";
  const originalResponse = await page.request.get(endpoint);
  expect(originalResponse.status()).toBe(200);
  const original = await originalResponse.json() as {
    revision: number; active_persona_id: string | null; show_persona_selector: boolean;
  };
  expect(Number.isSafeInteger(original.revision)).toBe(true);
  expect(original.show_persona_selector,
    "The approved persona acceptance principal must permit the selector").toBe(true);

  const catalogResponse = await page.request.get("/api/personas/");
  expect(catalogResponse.status()).toBe(200);
  const catalog = await catalogResponse.json() as Array<{
    id: string; name: string; is_active: boolean;
  }>;
  expect(Array.isArray(catalog)).toBe(true);
  const alternative = catalog.find(persona =>
    persona.is_active === true && typeof persona.id === "string" &&
    persona.id.length > 0 && persona.id !== original.active_persona_id);
  expect(alternative,
    "Approved persona acceptance needs a different active catalog persona").toBeDefined();
  if (!alternative) return;

  let runs = 0;
  page.context().on("request", request => {
    if (request.method() === "POST" && isInferenceRequest(request.url())) runs++;
  });
  await page.goto("/acceptance/copilotkit/" + encodeURIComponent(conversationId));
  const selector = page.getByRole("combobox", { name: "Active Karen persona" });
  await expect(selector).toHaveValue(original.active_persona_id ?? "");

  try {
    // Observe the actual unmocked browser PUT, not only a React state change.
    const written = page.waitForResponse(response =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname === endpoint,
      { timeout: 15000 },
    );
    await selector.selectOption(alternative.id);
    const savedResponse = await written;
    expect(savedResponse.status(), "Persona switch must be accepted by canonical CAS").toBe(200);
    const saved = await savedResponse.json() as {
      revision: number; active_persona_id: string | null;
    };
    expect(saved.revision).toBe(original.revision + 1);
    expect(saved.active_persona_id).toBe(alternative.id);
    await expect(selector).toHaveValue(alternative.id);
    await page.reload();
    await expect(page.getByRole("combobox", { name: "Active Karen persona" }))
      .toHaveValue(alternative.id, { timeout: 30000 });
    const persisted = await page.request.get(endpoint);
    expect(persisted.status()).toBe(200);
    const confirmed = await persisted.json() as {
      revision: number; active_persona_id: string | null;
    };
    expect(confirmed.revision).toBe(saved.revision);
    expect(confirmed.active_persona_id).toBe(alternative.id);
    expect(runs, "Persona changes must never start a model").toBe(0);
  } finally {
    // Restore only if this test's own revision is still current. Never
    // overwrite a newer preference written by another window or actor.
    const latest = await page.request.get(endpoint);
    expect(latest.status(), "Persona cleanup requires verified current state").toBe(200);
    const value = await latest.json() as {
      revision: number; active_persona_id: string | null;
    };
    if (value.active_persona_id === alternative.id &&
        value.revision === original.revision + 1) {
      const restored = await page.request.put(endpoint, {
        data: {
          active_persona_id: original.active_persona_id,
          expected_revision: value.revision,
        },
      });
      expect(restored.status(), "Persona restoration must be CAS-confirmed").toBe(200);
      const confirmed = await restored.json() as {
        revision: number; active_persona_id: string | null;
      };
      expect(confirmed.active_persona_id).toBe(original.active_persona_id);
      expect(confirmed.revision).toBe(value.revision + 1);
    } else {
      // A concurrent new writer won. Do not falsely report this test's
      // preference restoration or clobber that newer user's choice.
      expect(value.active_persona_id,
        "Persona changed concurrently: refusing to overwrite the newer selection")
        .toBe(original.active_persona_id);
    }
  }
});

/**
 * Negative-path live cancellation proof only. A fresh absent transport run ID
 * cannot refer to any approved model execution and must not mutate history.
 * This deliberately does NOT prove a real worker was cancelled.
 */
test("CK-07F rejects runless and nonexistent stop requests without changing saved conversation", async ({ page }) => {
  requireApprovedNativeFixture();
  if (!email || !password || !conversationId) return;
  await signInApprovedKaren(page, email, password);

  const threadUrl = "/api/copilotkit/threads/" +
    encodeURIComponent(conversationId) + "/messages";
  const draftUrl = "/api/conversations/" +
    encodeURIComponent(conversationId) + "/draft";
  const stopUrl = "/api/copilotkit/agent/default/stop/" +
    encodeURIComponent(conversationId);
  const beforeThread = await page.request.get(threadUrl);
  const beforeDraft = await page.request.get(draftUrl);
  expect(beforeThread.status(), "Requires an authenticated owned canonical thread").toBe(200);
  expect(beforeDraft.status(), "Requires authenticated canonical draft").toBe(200);
  const history = await beforeThread.json();
  const draft = await beforeDraft.json();

  const forbidden: string[] = [];
  page.context().on("request", request => {
    if (request.method() === "POST" && isInferenceRequest(request.url())) {
      forbidden.push(new URL(request.url()).pathname);
    }
  });

  // Mount the actual native view under the same authenticated principal.
  // The event listener is intentionally scoped to browser-driven requests;
  // APIRequestContext calls below are explicit probes, not UI traffic.
  await page.goto("/acceptance/copilotkit/" + encodeURIComponent(conversationId));
  await expect(page.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
    timeout: 30000,
  });
  expect(forbidden, "Opening native chat must not start inference").toEqual([]);

  // Missing exact run identity is rejected before backend cancellation.
  const runless = await page.request.post(stopUrl, {
    data: { threadId: conversationId },
  });
  expect(runless.status()).toBe(422);
  expect(JSON.stringify(await runless.json())).not.toContain("cancelled");

  // Use a high-entropy absent identifier, not an arbitrary known run.
  // The canonical backend still repeats tenant, user and conversation checks.
  const impossibleId = "ck07_absent_" + crypto.randomUUID().replace(/-/g, "");
  const unknown = await page.request.post(stopUrl, {
    data: { runId: impossibleId },
  });
  expect(unknown.status(), "Absent scoped run must not appear cancellable").toBe(404);
  expect(JSON.stringify(await unknown.json())).not.toContain("cancellation_confirmed");

  const afterThread = await page.request.get(threadUrl);
  const afterDraft = await page.request.get(draftUrl);
  expect(afterThread.status()).toBe(200);
  expect(afterDraft.status()).toBe(200);
  expect(await afterThread.json(), "Rejected stop must not fabricate a history change")
    .toEqual(history);
  expect(await afterDraft.json(), "Rejected stop must not alter any unsent draft")
    .toEqual(draft);
  expect(forbidden, "Invalid stop must never execute inference").toEqual([]);
});

/**
 * Positive cancellation proof is MUTATING and requires a separate disposable,
 * owner-scoped conversation and explicit approval to invoke a real model.
 * It never uses mock AG-UI frames, a synthetic worker or invented receipts.
 * This is single-deployment worker proof, not a cross-worker guarantee.
 */
test("CK-07F3 operator-approved real native stop confirms the durable worker outcome", async ({ page }) => {
  const enabled = process.env.KAREN_COPILOTKIT_LIVE_STOP_REQUIRED === "true";
  test.skip(!enabled, "Real model cancellation requires an approved disposable conversation");
  requireApprovedNativeFixture();
  const dedicatedThread = process.env.KAREN_COPILOTKIT_LIVE_STOP_CONVERSATION_ID;
  if (!dedicatedThread || !UUID.test(dedicatedThread) || dedicatedThread === conversationId) {
    throw new Error("Live Stop requires a distinct valid, disposable owned conversation UUID");
  }
  if (!email || !password) throw new Error("Approved sanitized sign-in required");
  test.setTimeout(240000);
  await signInApprovedKaren(page, email, password);

  const capabilities = await page.request.get("/api/chat/ag-ui/capabilities");
  expect(capabilities.status()).toBe(200);
  const flags = await capabilities.json() as {
    enabled: boolean; governed_history: boolean;
  };
  expect(flags.enabled, "Real execution must use enabled canonical AG-UI").toBe(true);
  expect(flags.governed_history, "Positive stop needs durable run admission").toBe(true);

  const prefix = "/api/copilotkit/threads/" + encodeURIComponent(dedicatedThread);
  const before = await page.request.get(prefix + "/messages");
  expect(before.status()).toBe(200);
  const original = await before.json() as {
    threadId: string; messages: Array<{ id: string; role: string; content: string }>;
  };
  expect(original.threadId).toBe(dedicatedThread);
  expect(original.messages, "Live Stop uses an empty disposable conversation").toEqual([]);
  const draftUrl = "/api/conversations/" + encodeURIComponent(dedicatedThread) + "/draft";
  const draft = await page.request.get(draftUrl);
  expect(draft.status()).toBe(200);
  expect((await draft.json() as { text: string }).text,
    "Disposable conversation must not contain another person's unsent draft").toBe("");

  await page.goto("/acceptance/copilotkit/" + encodeURIComponent(dedicatedThread));
  const native = page.getByTestId("karen-copilot-controlled-chat");
  await expect(native).toBeVisible({ timeout: 30000 });
  // Voice buttons and failed-message controls are siblings, not inference
  // controls. Only interact with the uniquely scoped SDK composer.
  const sdkChat = native.getByTestId("karen-copilot-sdk-chat");
  await expect(sdkChat).toBeVisible();
  const composer = sdkChat.locator("textarea");
  await expect(composer, "Native SDK must expose exactly one composer").toHaveCount(1);
  const prompt = "CK-07F3 approved disposable model cancellation: explain a detailed multi-stage thought experiment about sorting 100000 numbered tiles.";
  await composer.fill(prompt);
  await expect.poll(async () => {
    const value = await page.request.get(draftUrl);
    expect(value.status()).toBe(200);
    return (await value.json() as { text: string }).text;
  }, { timeout: 20000 }).toBe(prompt);

  // Observe the real SDK transport POST. Never log prompt, cookies or streamed
  // model output, and do not supply a fabricated AG-UI runId.
  const submitted = page.waitForRequest(request =>
    request.method() === "POST" &&
    new URL(request.url()).pathname === "/api/copilotkit/agent/default/run",
    { timeout: 30000 },
  );
  await composer.press("Enter");
  const runRequest = await submitted;
  const payload = runRequest.postDataJSON() as { threadId: string; runId: string };
  expect(payload.threadId).toBe(dedicatedThread);
  expect(RUN_ID.test(payload.runId), "Observe a real SDK-issued run identity").toBe(true);

  // A client transport packet alone does not establish that Karen admitted
  // this run. Require a separate owner-scoped PostgreSQL-backed status GET
  // to see the exact SDK run ID in the canonical running state before Stop.
  const runStatusUrl = "/api/copilotkit/agent/default/runs/" +
    dedicatedThread + "/" + payload.runId + "/status";
  await expect.poll(async () => {
    const status = await page.request.get(runStatusUrl);
    if (status.status() === 404) return "not-admitted";
    expect(status.status(), "Canonical run status must be readable").toBe(200);
    const body = await status.json() as {
      status: string; cancel_requested: boolean; cancellation_confirmed: boolean;
    };
    expect(body.cancel_requested).toBe(false);
    expect(body.cancellation_confirmed).toBe(false);
    return body.status;
  }, { timeout: 15000, intervals: [100, 200, 300, 500] }).toBe("running");

  // If the model finishes before Stop is available, this test fails rather
  // than interpreting a completed run as successful cancellation.
  // Never click Stop dictation or any other similarly named sibling.
  // An ambiguous SDK Stop is a test failure, never an arbitrary first match.
  const stop = sdkChat.getByRole("button", { name: /stop/i });
  await expect(stop, "Require one and only one SDK inference Stop").toHaveCount(1, {
    timeout: 20000,
  });
  await expect(stop).toBeVisible();
  await expect(stop).toBeEnabled();
  const stopUrl = "/api/copilotkit/agent/default/stop/" + dedicatedThread;
  const outboundStops: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" &&
        new URL(request.url()).pathname === stopUrl) {
      outboundStops.push(request.postData() ?? "");
    }
  });
  const stopReceipt = page.waitForResponse(response =>
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === stopUrl,
    { timeout: 20000 },
  );
  await stop.click();
  const response = await stopReceipt;
  expect(outboundStops, "Native Stop must target exactly one observed run")
    .toEqual([JSON.stringify({ runId: payload.runId })]);
  expect([200, 202], "Stop must be accepted by the canonical owned-run gateway")
    .toContain(response.status());
  const receipt = await response.json() as {
    status: string; cancel_requested: boolean; cancellation_confirmed: boolean;
  };
  expect(receipt.cancel_requested).toBe(true);
  expect(["cancelling", "cancelled"]).toContain(receipt.status);
  expect(receipt.cancellation_confirmed).toBe(receipt.status === "cancelled");

  if (!receipt.cancellation_confirmed) {
    await expect(native.getByTestId("karen-copilot-stop-status"))
      .toContainText("confirmation is still pending");
    await expect.poll(async () => {
      const check = native.getByRole("button", { name: "Check cancellation status" });
      if (await check.isVisible()) {
        await expect(check).toBeEnabled();
        await check.click();
      }
      return (await native.getByTestId("karen-copilot-stop-status").textContent()) ?? "";
    }, { timeout: 100000, intervals: [1500, 2000, 3000] })
      .toContain("Karen confirmed this run was cancelled.");
  }

  // Even an immediate 200 stop must be reflected in the actual native
  // UI, not only in a server JSON payload.
  await expect(native.getByTestId("karen-copilot-stop-status"))
    .toContainText("Karen confirmed this run was cancelled.");
  const terminal = await page.request.get(runStatusUrl);
  expect(terminal.status(), "Read-only canonical run status must be available").toBe(200);
  expect(await terminal.json()).toEqual({
    status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
  });
  const stored = await page.request.get(prefix + "/messages");
  expect(stored.status()).toBe(200);
  const persisted = await stored.json() as {
    threadId: string; messages: Array<{ id: string; role: string; content: string }>;
  };
  expect(persisted.threadId).toBe(dedicatedThread);
  expect(persisted.messages.filter(m => m.role === "assistant"),
    "Cancelled run must not create a falsely completed assistant transcript")
    .toEqual([]);
  // The disposable conversation is intentionally retained as audit evidence.
  // No user-facing fixture or production message is ever deleted as cleanup.
});

/**
 * Read-only consumer-adapter proof using the same approved owned conversation.
 * The SessionProvider is real; never replace it with a browser-owned thread.
 * No provider selection, session creation, or model execution is performed.
 */
test("CK-CONSUMER-01 gated consumer preview restores an owned session without inference", async ({ page }) => {
  requireApprovedNativeFixture();
  if (!email || !password || !conversationId) return;
  await signInApprovedKaren(page, email, password);

  const owned = await page.request.get(
    "/api/conversations/" + encodeURIComponent(conversationId),
  );
  expect(owned.status(), "Consumer preview requires an owned canonical conversation").toBe(200);

  const inferred: string[] = [];
  page.context().on("request", request => {
    if (request.method() === "POST" && isInferenceRequest(request.url())) {
      inferred.push(new URL(request.url()).pathname);
    }
  });

  const previewPath = "/acceptance/copilotkit-consumer/" + encodeURIComponent(conversationId);
  await page.goto(previewPath);
  await expect(page.getByTestId("karen-copilot-consumer-acceptance")).toBeVisible();
  await expect(page.getByTestId("karen-copilot-consumer-chat")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByTestId("karen-copilot-sdk-chat")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByTestId("karen-copilot-model-discovery")).toBeVisible();
  await expect(page.getByRole("button", { name: "Find conversations" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "New conversation" })).toBeEnabled();
  expect(inferred, "Opening a saved consumer thread must not start inference").toEqual([]);

  await page.getByRole("button", { name: "Find conversations" }).click();
  await expect(page.getByRole("searchbox", { name: "Find a conversation" })).toBeVisible();
  await page.getByRole("button", { name: "Find conversations" }).click();
  await expect(page.getByRole("searchbox", { name: "Find a conversation" })).toHaveCount(0);
  expect(inferred, "History navigation must be read-only").toEqual([]);

  await page.reload();
  await expect(page.getByTestId("karen-copilot-consumer-chat")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByTestId("karen-copilot-sdk-chat")).toBeVisible();
  expect(inferred, "Consumer reload must not create a model run").toEqual([]);

  await page.goto("/dashboard");
  await expect(page.getByTestId("karen-assistant-ui-chat")).toBeVisible();
  expect(inferred, "Ordinary dashboard remains on the existing consumer mount").toEqual([]);
});
