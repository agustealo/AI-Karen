import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { Page } from "@playwright/test";

/**
 * The preview route previously owned this CSS, so the dashboard could render
 * an unstyled SDK and still pass preview-only acceptance. Assert the real
 * browser loaded the *nonempty same-origin* pinned vendor stylesheet.
 */
/**
 * Read canonical JSON through the *actual signed-in browser*. Playwright's
 * request context shares cookies, but cannot see Karen's localStorage Bearer
 * access token. Keep that credential inside the browser: never echo it to the
 * runner, attach it to redirects or send it to a different origin.
 */
async function readAuthorizedSameOriginJson(
  page: Page, apiPath: string,
): Promise<{ ok: boolean; body: unknown }> {
  return page.evaluate(async (path) => {
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      throw new Error("Refusing authenticated read outside the application's API origin");
    }
    const accessToken = window.localStorage.getItem("access_token");
    const response = await window.fetch(url.pathname + url.search, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    return { ok: response.ok, body: response.ok ? await response.json() : null };
  }, apiPath);
}

/**
 * Model text alone is insufficient release proof: backend-saved execution
 * provenance must be bound to the precise persisted assistant turn. The
 * thread gateway already verifies this snapshot before the SDK displays it.
 * Do not infer a model from the configured preference or the chat UI.
 */
async function expectVerifiedExecutionReceipt(
  page: Page, conversationId: string, persistedAnswer: string,
): Promise<void> {
  await expect.poll(async () => {
    const { ok, body } = await readAuthorizedSameOriginJson(
      page, `/api/copilotkit/threads/${conversationId}/messages`,
    );
    if (!ok || !body || typeof body !== "object") return false;
    const response = body as Record<string, unknown>;
    if (response.threadId !== conversationId ||
        !Array.isArray(response.messages) || !Array.isArray(response.replayEvents)) return false;
    const matching = response.messages.filter((item): item is Record<string, unknown> =>
      item !== null && typeof item === "object" && !Array.isArray(item) &&
      item.role === "assistant" && item.content === persistedAnswer &&
      typeof item.id === "string" && item.id.length > 0);
    if (matching.length !== 1) return false;

    const receipts = response.replayEvents.filter((item): item is Record<string, unknown> =>
      item !== null && typeof item === "object" && !Array.isArray(item) &&
      item.type === "CUSTOM" && item.name === "karen.execution_receipt.v1" &&
      item.messageId === matching[0].id);
    if (receipts.length !== 1) return false;
    const receipt = receipts[0].value;
    if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) return false;
    const metadata = receipt as Record<string, unknown>;
    // Reject configured-only or unavailable executors. A legitimate runtime
    // fallback may change provider/model, so do not hardcode provider names.
    const required = ["actual_provider", "actual_model", "response_source"] as const;
    if (required.some(key => typeof metadata[key] !== "string" ||
        !(metadata[key] as string).trim() ||
        ["unknown", "none", "unavailable"].includes((metadata[key] as string).trim().toLowerCase()))) {
      return false;
    }
    // A persisted assistant turn and a populated provider/model do not prove
    // model execution if the response itself came from memory, a tool, a
    // canned fallback, or replay. Require a generative provenance category.
    // This is provider-agnostic and accepts local, remote and fallback models.
    const responseSource = (metadata.response_source as string).trim().toLowerCase();
    return /(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/.test(responseSource);
  }, {
    timeout: 30_000,
    intervals: [500, 1000, 2000],
    message: "The exact saved assistant turn must have backend-verified model execution provenance",
  }).toBe(true);
}

/**
 * A matching Next.js SHA does not establish that the canonical API exists.
 * Do not send approved login credentials to a frontend whose backend is down.
 * The same fail-closed readiness contract is enforced by the workflow's
 * independent verify_deployment_revision.py before Playwright starts.
 */
async function requireLiveCanonicalBackend(page: Page, target: URL): Promise<void> {
  const response = await page.context().request.get(
    new URL("/api/health", target).toString(),
    { failOnStatusCode: false, maxRedirects: 0, timeout: 20_000 },
  );
  expect(response.status(), "Canonical API must be reachable before authenticated browser acceptance").toBe(200);
  expect(response.headers()["content-type"] ?? "").toMatch(/^application\/json(?:;|$)/i);
  expect(response.headers()["cache-control"] ?? "").toContain("no-store");
  const payload: unknown = await response.json();
  expect(payload, "Canonical backend health must contain a verified ready state").toEqual({
    status: "ok",
    backend_ready: true,
  });
}

async function expectRealCopilotKitStyles(page: Page): Promise<void> {
  const selector = 'link[rel="stylesheet"][href="/vendor/copilotkit-v2.css"]';
  await expect(page.locator(selector)).toHaveCount(1);
  await expect.poll(async () => page.evaluate((linkSelector) => {
    const link = document.querySelector<HTMLLinkElement>(linkSelector);
    if (!link?.sheet) return false;
    try {
      return link.sheet.cssRules.length > 0;
    } catch {
      return false;
    }
  }, selector), {
    timeout: 30_000,
    message: "The actual dashboard must load nonempty CopilotKit vendor CSS",
  }).toBe(true);
}


/**
 * Release-only, real-browser boot proof for the canonical CopilotKit chat.
 * Runs against an approved HTTPS deployment with a matching source revision
 * and a genuinely reachable canonical API. No route mocks or synthetic replies.
 *
 * Required when KAREN_CHAT_BOOT_ACCEPTANCE=1:
 *   KAREN_BASE_URL=<approved clean HTTPS origin>
 *   KAREN_CHAT_BOOT_REVISION=<exact expected full commit SHA>
 *   KAREN_E2E_AUTH_STATE=<preapproved storage state>, or the workflow's
 *   KAREN_UX_EMAIL and KAREN_UX_PASSWORD for approved sign-in.
 *
 * The served application must expose its canonical deployed revision at
 * /api/deployment-revision. This test fails closed if that is unavailable.
 * Never attach authenticated traces, screenshots or videos to public CI.
 */
const releaseMode = process.env.KAREN_CHAT_BOOT_ACCEPTANCE === "1";
const localMode = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const enabled = releaseMode || localMode;
const authState = process.env.KAREN_E2E_AUTH_STATE;
const expectedRevision = process.env.KAREN_CHAT_BOOT_REVISION;
const approvedUrl = process.env.KAREN_BASE_URL;
const approvedEmail = process.env.KAREN_UX_EMAIL;
const approvedPassword = process.env.KAREN_UX_PASSWORD;

if (releaseMode && localMode) {
  throw new Error("Local and release chat boot acceptance cannot run in the same invocation");
}

if (enabled) {
  if (!(authState || (approvedEmail && approvedPassword)) || !approvedUrl) {
    throw new Error("Chat boot acceptance requires an explicit target and approved authentication");
  }
  let target: URL;
  try {
    target = new URL(approvedUrl);
  } catch {
    throw new Error("Chat boot acceptance requires a valid target origin");
  }
  if (target.username || target.password || target.pathname !== "/" ||
      target.search || target.hash ||
      (localMode && (
        !target.port ||
        target.protocol !== "http:" ||
        !["localhost", "127.0.0.1"].includes(target.hostname)
      )) ||
      (releaseMode && (
        target.protocol !== "https:" || target.port !== "" ||
        !expectedRevision || !/^[0-9a-f]{40}$/i.test(expectedRevision)
      ))) {
    throw new Error("Chat boot acceptance target, revision or execution mode is invalid");
  }
}

async function requireReviewedRevision(page: Page, target: URL): Promise<void> {
  // Local dev builds may not expose an attested deployment revision. Release
  // acceptance always requires the exact reviewed SHA and cannot skip it.
  if (!releaseMode) return;
  const response = await page.context().request.get(
    new URL("/api/deployment-revision", target).toString(),
    { failOnStatusCode: false, maxRedirects: 0, timeout: 20_000 },
  );
  expect(response.status()).toBe(200);
  const body: unknown = await response.json();
  expect(body).toBeTruthy();
  const revision = body as Record<string, unknown>;
  expect(revision.revision ?? revision.sha ?? revision.commit_sha ?? revision.git_sha)
    .toBe(expectedRevision);
}

test.use({
  storageState: authState || { cookies: [], origins: [] },
  trace: "off",
  screenshot: "off",
  video: "off",
});

test.describe("canonical consumer chat cold-load acceptance", () => {
  test.skip(!enabled, "Set KAREN_LOCAL_CHAT_ACCEPTANCE=1 or KAREN_CHAT_BOOT_ACCEPTANCE=1 for real backend/browser proof");

  test("persists a real user message and a real assistant reply", async ({ page }) => {
    test.setTimeout(180_000);
    const target = new URL(approvedUrl!);
    const browserErrors: string[] = [];
    page.on("pageerror", error => {
      browserErrors.push(`Uncaught page error: ${error.message}`);
    });
    page.on("console", message => {
      if (message.type() === "error" &&
          /ChunkLoadError|Loading chunk|web-inspector|Failed to fetch dynamically imported module/i.test(message.text())) {
        browserErrors.push(`Console chunk error: ${message.text()}`);
      }
    });
    page.on("response", response => {
      if (response.status() >= 400 && /\/_next\/static\/chunks\//.test(response.url())) {
        browserErrors.push(`Chunk HTTP ${response.status()}: ${response.url()}`);
      }
    });
    page.on("requestfailed", failedRequest => {
      if (/\/_next\/static\/chunks\//.test(failedRequest.url())) {
        browserErrors.push(`Chunk request failed: ${failedRequest.url()}`);
      }
    });
    page.on("request", assetRequest => {
      if (/\/_next\/static\/chunks\/.*(?:copilotkit[_/-])?web-inspector/i.test(assetRequest.url())) {
        browserErrors.push("Disabled CopilotKit inspector requested a browser chunk");
      }
    });
    await requireReviewedRevision(page, target);
    await requireLiveCanonicalBackend(page, target);

    if (!authState) {
      await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
    }
    await page.goto(new URL("/dashboard", target).toString());
    const shell = page.getByTestId("karen-copilot-consumer-chat");
    const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await shell.isVisible().catch(() => false)) &&
        await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);

    // Never inject acceptance prompts into an arbitrary existing user thread.
    // Create a separate durable conversation through the actual user UI.
    const previousId = await shell.getAttribute("data-conversation-id");
    const newConversation = shell.getByRole("button", { name: "New conversation" });
    await expect(newConversation, "Acceptance must be able to start a dedicated conversation").toBeVisible();
    await newConversation.click();
    await expect.poll(async () => {
      const nextId = await shell.getAttribute("data-conversation-id");
      return nextId !== null && nextId !== previousId ? nextId : null;
    }, { timeout: 30_000 }).not.toBeNull();
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);

    const id = await shell.getAttribute("data-conversation-id");
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    const prompt = `Karen live acceptance ${crypto.randomUUID()}: Please respond with a brief greeting.`;
    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer, "CopilotKit must present a usable composer").toBeVisible();
    // This must reproduce the original consumer defect: Enter immediately
    // after typing while the debounced draft CAS may still be pending.
    // Waiting for autosave here would make the acceptance test meaningless.
    const observedRunRequests: string[] = [];
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (request.method() === "POST" && (
        pathname === "/api/copilotkit/agent/default/run" ||
        pathname === "/api/chat/ag-ui" ||
        pathname === "/api/chat/stream"
      )) {
        observedRunRequests.push(pathname);
      }
    });
    const draftEndpoint = `/api/conversations/${id}/draft`;
    await composer.fill(prompt);
    await composer.press("Enter");

    const endpoint = `/api/conversations/${id}`;
    let persistedAnswer = "";
    await expect.poll(async () => {
      const { ok, body } = await readAuthorizedSameOriginJson(page, endpoint);
      if (!ok || !body || typeof body !== "object" ||
          !Array.isArray((body as Record<string, unknown>).messages)) {
        return false;
      }
      const messages = (body as { messages: Array<{ role?: string; content?: string }> }).messages;
      const matchingPromptIndices = messages.flatMap((message, index) =>
        message.role === "user" && message.content === prompt ? [index] : []);
      // A unique submitted turn must occur exactly once, and its immediate
      // successor must be the model reply. A reply to an unrelated later turn
      // cannot satisfy the acceptance contract.
      const promptIndex = matchingPromptIndices[0];
      const assistant = matchingPromptIndices.length === 1
        ? messages[promptIndex + 1]
        : undefined;
      const accepted = assistant?.role === "assistant" &&
        typeof assistant.content === "string" && assistant.content.trim().length > 0;
      persistedAnswer = accepted ? assistant.content! : "";
      return accepted;
    }, {
      timeout: 120_000,
      intervals: [1000, 2000, 3000],
      message: "A real user turn and subsequent assistant response must be persisted by the canonical backend",
    }).toBe(true);
    expect(persistedAnswer.trim().length).toBeGreaterThan(0);
    expect(
      observedRunRequests,
      "One immediate Enter must send exactly one model execution request",
    ).toHaveLength(1);
    await expect.poll(async () => {
      const { ok, body: draft } = await readAuthorizedSameOriginJson(page, draftEndpoint);
      return Boolean(ok && draft && typeof draft === "object" &&
        (draft as { text?: unknown }).text === "");
    }, {
      timeout: 30_000,
      intervals: [250, 500, 1000],
      message: "Immediate Enter must consume the persisted draft without leaving stale text",
    }).toBe(true);
    await expectVerifiedExecutionReceipt(page, id!, persistedAnswer);
    // A saved backend answer alone is not a functioning consumer chat.
    // The active CopilotKit view must render the real assistant response
    // before any reload, not only during a later history replay.
    await expect(
      shell.getByTestId("karen-copilot-assistant-message").filter({ hasText: persistedAnswer }).last(),
      "The live chat must render the persisted assistant reply before reload",
    ).toBeVisible({ timeout: 30_000 });

    await page.reload();
    const restored = page.getByTestId("karen-copilot-consumer-chat");
    if (!(await restored.isVisible().catch(() => false)) &&
        await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(restored).toHaveAttribute("data-conversation-id", id!);
    await expect(restored.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);
    await expectVerifiedExecutionReceipt(page, id!, persistedAnswer);
    await expect(restored.getByTestId("karen-copilot-rail-unverified")).toHaveCount(0, {
      timeout: 30_000,
    });
    await expect(restored.getByText(prompt, { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(
      restored.getByTestId("karen-copilot-assistant-message").filter({ hasText: persistedAnswer }).last(),
      "The actual persisted assistant reply must be rendered after reload",
    ).toBeVisible({ timeout: 30_000 });
    expect(browserErrors, "Chat submit and restore must not cause browser or chunk errors").toEqual([]);
  });

  for (const scenario of [
    {
      label: "time", prompt: "What time is it?",
      component: "time.observation", testId: "karen-time-presentation",
    },
    {
      label: "weather", prompt: "What's the weather in Detroit, Michigan right now?",
      component: "weather.observation", testId: "karen-weather-presentation",
    },
    {
      label: "search", prompt: "Search the internet for the latest NASA news today.",
      component: "search.results", testId: "karen-search-results",
    },
    {
      label: "news", prompt: "Latest news about NASA",
      component: "search.results", testId: "karen-search-results",
    },
    {
      label: "current movies", prompt: "Show me the latest movies",
      component: "search.results", testId: "karen-search-results",
    },
    {
      label: "current movie source table", prompt: "Latest movies in a table",
      component: "data.table", testId: "karen-data-table",
    },
  ] as const) {
  test(`one first ${scenario.label} prompt renders backend-attested UI immediately and after reload`, async ({ page }) => {
    test.setTimeout(240_000);
    const target = new URL(approvedUrl!);
    await requireReviewedRevision(page, target);
    await requireLiveCanonicalBackend(page, target);

    if (!authState) {
      await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
    }
    await page.goto(new URL("/dashboard", target).toString());

    const shell = page.getByTestId("karen-copilot-consumer-chat");
    const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await shell.isVisible().catch(() => false)) &&
        await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });

    // Never touch a real user's existing conversation during release proof.
    const previousId = await shell.getAttribute("data-conversation-id");
    const newConversation = shell.getByRole("button", { name: "New conversation" });
    await expect(newConversation).toBeVisible();
    await newConversation.click();
    await expect.poll(async () => {
      const selected = await shell.getAttribute("data-conversation-id");
      return selected && selected !== previousId ? selected : null;
    }, { timeout: 30_000 }).not.toBeNull();
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible();
    await expectRealCopilotKitStyles(page);

    const conversationId = await shell.getAttribute("data-conversation-id");
    expect(conversationId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    const prompt = scenario.prompt;
    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer).toBeVisible();

    // Observe the actual SDK send. A retry, second Enter, or hidden duplicate
    // execution must not be needed to produce the first generated surface.
    const observedRunRequests: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST" && (
        path === "/api/copilotkit/agent/default/run" ||
        path === "/api/chat/ag-ui" ||
        path === "/api/chat/stream"
      )) {
        observedRunRequests.push(path);
      }
    });
    const browserErrors: string[] = [];
    page.on("pageerror", error => { browserErrors.push(error.message); });
    page.on("console", message => {
      if (message.type() === "error" &&
          /ChunkLoadError|web-inspector|Failed to fetch dynamically imported module/i.test(message.text())) {
        browserErrors.push(message.text());
      }
    });

    await composer.fill(prompt);
    await composer.press("Enter");

    // A replay-only implementation must not pass first-turn acceptance.
    // Require the live CopilotKit view to render its verified surface before
    // this test requests the persisted transcript or reloads the thread.
    // This verifies first-send delivery, not subsecond streaming latency.
    const visibleCard = shell.getByTestId(scenario.testId);
    await expect(visibleCard, "The first prompt must render a live card before transcript inspection")
      .toHaveCount(1, { timeout: 30_000 });
    await expect(visibleCard).toBeVisible();

    // Now independently verify that the same card was durably saved to the
    // exact assistant reply, not inferred client-side or fetched from replay.
    let savedAnswer = "";
    let savedAssistantId = "";
    let savedPresentationId = "";
    await expect.poll(async () => {
      const { ok, body } = await readAuthorizedSameOriginJson(
        page, `/api/copilotkit/threads/${conversationId}/messages`,
      );
      if (!ok || !body || typeof body !== "object") return false;
      const snapshot = body as Record<string, unknown>;
      if (snapshot.threadId !== conversationId ||
          !Array.isArray(snapshot.messages) ||
          !Array.isArray(snapshot.replayEvents)) return false;
      const messages = snapshot.messages as Record<string, unknown>[];
      const promptPositions = messages.flatMap((message, index) =>
        message?.role === "user" && message.content === prompt ? [index] : []);
      if (promptPositions.length !== 1) return false;
      const reply = messages[promptPositions[0] + 1];
      if (reply?.role !== "assistant" || typeof reply.id !== "string" ||
          !reply.id || typeof reply.content !== "string" || !reply.content.trim()) return false;
      const timeEvents = (snapshot.replayEvents as Record<string, unknown>[]).filter(event => {
        if (!event || event.type !== "CUSTOM" ||
            event.name !== "karen.presentation.v1" ||
            event.messageId !== reply.id ||
            !event.value || typeof event.value !== "object" ||
            Array.isArray(event.value)) return false;
        const value = event.value as Record<string, unknown>;
        if (value.component_type === scenario.component) return true;
        if (value.component_type !== "surface.composition" ||
            !value.data || typeof value.data !== "object" ||
            Array.isArray(value.data)) return false;
        const items = (value.data as Record<string, unknown>).items;
        return Array.isArray(items) && items.some(item =>
          item && typeof item === "object" && !Array.isArray(item) &&
          item.component_type === scenario.component);
      });
      if (timeEvents.length !== 1) return false;
      const presentation = timeEvents[0].value as Record<string, unknown>;
      // A direct observation has evidence but no model invocation. Validate
      // the server-attested evidence binding rather than fabricating a model
      // execution receipt for a source-only time/weather answer.
      if (presentation.schema_version !== 1 ||
          typeof presentation.presentation_id !== "string" ||
          !presentation.presentation_id ||
          typeof presentation.evidence_ref !== "string" ||
          !presentation.evidence_ref.trim() ||
          typeof presentation.correlation_id !== "string" ||
          !presentation.correlation_id.trim()) return false;

      const receipts = (snapshot.replayEvents as Record<string, unknown>[]).filter(event =>
        event && event.type === "CUSTOM" &&
        event.name === "karen.execution_receipt.v1" &&
        event.messageId === reply.id);
      if (receipts.length > 1) return false;
      // When grounded synthesis truly ran an LLM, its receipt must identify
      // the actual executor. A pure tool observation correctly has none.
      if (receipts.length === 1) {
        const receipt = receipts[0].value;
        if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) return false;
        const model = receipt as Record<string, unknown>;
        if (["actual_provider", "actual_model", "response_source"].some(key =>
          typeof model[key] !== "string" || !(model[key] as string).trim() ||
          ["unknown", "none", "unavailable"].includes(
            (model[key] as string).trim().toLowerCase()
          ))) return false;
        // An observed model receipt must attest generation, not a tool,
        // static fallback or stale memory response with populated attribution.
        const responseSource = (model.response_source as string).trim().toLowerCase();
        if (!/(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/.test(responseSource)) {
          return false;
        }
      }
      savedAnswer = reply.content;
      savedAssistantId = reply.id;
      savedPresentationId = presentation.presentation_id;
      return true;
    }, {
      timeout: 120_000,
      intervals: [500, 1000, 2000],
      message: "First prompt must persist one backend-attested rich surface attached to its assistant reply",
    }).toBe(true);

    const firstCardText = (await visibleCard.innerText()).trim();
    let originalSourceUrls: string[] = [];
    if (scenario.label === "time") {
      expect(firstCardText).toContain("Reported time");
    } else if (scenario.label === "weather") {
      expect(firstCardText).toContain("Source:");
    } else if (scenario.component === "data.table") {
      await expect(visibleCard.locator("table")).toHaveCount(1);
      await expect(visibleCard.locator("thead th")).toHaveCount(3);
      expect(firstCardText).toContain("Verified search source excerpts");
      expect(firstCardText).toContain("Source URL");
      // Source-backed table data must expose public source URLs, not actions
      // or model-invented citations. Other components retain link checks.
      const urlCells = await visibleCard.locator("tbody tr td:last-child").allInnerTexts();
      expect(urlCells.length, "The table must include verified sources").toBeGreaterThan(0);
      for (const url of urlCells) {
        const parsed = new URL(url.trim());
        expect(["https:", "http:"]).toContain(parsed.protocol);
        expect(parsed.username).toBe("");
        expect(parsed.password).toBe("");
        expect(parsed.hostname).not.toMatch(/^(?:localhost|127\.|10\.|192\.168\.)/);
      }
      const sourceLinks = visibleCard.locator("tbody tr td:last-child a");
      await expect(sourceLinks).toHaveCount(urlCells.length);
      for (let index = 0; index < urlCells.length; index += 1) {
        const link = sourceLinks.nth(index);
        await expect(link).toHaveAttribute("href", urlCells[index].trim());
        await expect(link).toHaveAttribute("rel", "noopener noreferrer");
        await expect(link).toHaveAttribute("target", "_blank");
      }
      await expect(visibleCard.locator("button")).toHaveCount(0);
    } else {
      expect(firstCardText).toContain("View source:");
      const links = visibleCard.locator('a[href^="https://"], a[href^="http://"]');
      expect(await links.count(), "Verified search cards must expose a source link").toBeGreaterThan(0);
      originalSourceUrls = await links.evaluateAll(nodes =>
        nodes.map(node => (node as HTMLAnchorElement).href),
      );
      // The browser must never make a source card carry an auth credential,
      // javascript URL, or a synthetic view URL instead of source evidence.
      for (const sourceUrl of originalSourceUrls) {
        const parsed = new URL(sourceUrl);
        expect(["https:", "http:"]).toContain(parsed.protocol);
        expect(parsed.username).toBe("");
        expect(parsed.password).toBe("");
        expect(parsed.hostname).not.toMatch(/^(?:localhost|127\.|10\.|192\.168\.)/);
      }
    }
    expect(observedRunRequests, "One first prompt must cause exactly one execution")
      .toHaveLength(1);

    await page.reload();
    const restored = page.getByTestId("karen-copilot-consumer-chat");
    const restoredLaunch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await restored.isVisible().catch(() => false)) &&
        await restoredLaunch.isVisible().catch(() => false)) {
      await restoredLaunch.click();
    }
    await expect(restored).toHaveAttribute("data-conversation-id", conversationId!);
    await expect(restored.getByTestId("karen-copilot-controlled-chat"))
      .toBeVisible({ timeout: 30_000 });
    await expectRealCopilotKitStyles(page);
    await expect(restored.getByTestId("karen-copilot-rail-unverified"))
      .toHaveCount(0, { timeout: 30_000 });
    await expect(restored.getByText(prompt, { exact: true })).toBeVisible();

    const restoredCard = restored.getByTestId(scenario.testId);
    await expect(restoredCard, "Reload must restore the actual verified UI surface")
      .toHaveCount(1, { timeout: 30_000 });
    expect((await restoredCard.innerText()).trim()).toBe(firstCardText);
    if (originalSourceUrls.length > 0) {
      const restoredSourceUrls = await restoredCard.locator(
        'a[href^="https://"], a[href^="http://"]',
      ).evaluateAll(nodes => nodes.map(node => (node as HTMLAnchorElement).href));
      expect(restoredSourceUrls, "The exact provider-verified source links must survive reload")
        .toEqual(originalSourceUrls);
    }
    const { ok, body } = await readAuthorizedSameOriginJson(
      page, `/api/copilotkit/threads/${conversationId}/messages`,
    );
    expect(ok).toBe(true);
    expect(body && typeof body === "object" && !Array.isArray(body)).toBe(true);
    const replaySnapshot = body as Record<string, unknown>;
    expect(replaySnapshot.threadId).toBe(conversationId);
    expect(Array.isArray(replaySnapshot.replayEvents)).toBe(true);
    const savedEvents = replaySnapshot.replayEvents as Array<{
      type?: unknown; name?: unknown; messageId?: unknown;
      value?: { presentation_id?: unknown };
    }>;
    const matchingPresentations = savedEvents.filter(event =>
      event.type === "CUSTOM" &&
      event.name === "karen.presentation.v1" &&
      event.messageId === savedAssistantId &&
      event.value?.presentation_id === savedPresentationId);
    expect(matchingPresentations, "The exact presentation must replay once on its original assistant turn")
      .toHaveLength(1);
    expect(savedEvents.filter(event =>
      event.type === "CUSTOM" &&
      event.name === "karen.presentation.v1" &&
      event.value?.presentation_id === savedPresentationId)).toHaveLength(1);
    expect(observedRunRequests).toHaveLength(1);
    expect(browserErrors).toEqual([]);
  });
  }

  test("boots, restores and loads assets without an inspector chunk failure", async ({ page }) => {
    test.setTimeout(120_000);
    const target = new URL(approvedUrl!);
    await requireReviewedRevision(page, target);
    await requireLiveCanonicalBackend(page, target);

    const failures: string[] = [];
    const capturePageFailure = (error: Error) => {
      failures.push(`Page exception: ${error.message}`);
    };
    page.on("pageerror", capturePageFailure);
    page.on("console", message => {
      if (message.type() === "error" &&
          /ChunkLoadError|Loading chunk|web-inspector|Failed to fetch dynamically imported module/i.test(message.text())) {
        failures.push(`Console chunk error: ${message.text()}`);
      }
    });
    page.on("response", response => {
      if (response.status() >= 400 &&
          /\/_next\/static\/chunks\//.test(response.url())) {
        failures.push(`Chunk HTTP ${response.status()}: ${response.url()}`);
      }
    });
    page.on("requestfailed", request => {
      if (/\/_next\/static\/chunks\//.test(request.url())) {
        failures.push(`Chunk request failed: ${request.url()} ${request.failure()?.errorText ?? ""}`);
      }
    });
    page.on("request", assetRequest => {
      if (/\/_next\/static\/chunks\/.*(?:copilotkit[_/-])?web-inspector/i.test(assetRequest.url())) {
        failures.push("Disabled CopilotKit inspector requested a browser chunk");
      }
    });

    if (!authState) {
      await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
    }

    let initialConversationId: string | null = null;
    for (const coldLoad of [true, false]) {
      if (coldLoad) {
        await page.goto(new URL("/dashboard", target).toString(), { waitUntil: "domcontentloaded" });
      } else {
        await page.reload({ waitUntil: "domcontentloaded" });
      }
      expect(new URL(page.url()).origin).toBe(target.origin);
      const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
      const shell = page.getByTestId("karen-copilot-consumer-chat");
      if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
        await launch.click();
      }
      await expect(shell, "Authenticated canonical CopilotKit chat must mount").toBeVisible({ timeout: 30_000 });
      await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({ timeout: 30_000 });
      await expectRealCopilotKitStyles(page);
      await expect(shell.getByRole("button", { name: "Find conversations" })).toBeVisible();
      await expect(shell.getByRole("button", { name: "Conversation options" })).toBeVisible();
      const conversationId = await shell.getAttribute("data-conversation-id");
      expect(conversationId, "Chat identity must be a canonical UUID").toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
      if (initialConversationId === null) {
        initialConversationId = conversationId;
      } else {
        expect(conversationId, "Reload must restore the same conversation identity").toBe(initialConversationId);
      }
      await page.waitForTimeout(750);
      expect(failures, "No chunk fetch errors or uncaught page exceptions are permitted").toEqual([]);
    }
  });
});
