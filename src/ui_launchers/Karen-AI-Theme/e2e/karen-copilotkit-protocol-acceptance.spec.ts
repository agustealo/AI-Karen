import { expect, test } from "./fixtures/verified-search-deployment";

// Authenticated requests read an approved real conversation; never write,
// start a model, capture browser state, or manufacture a saved AI response.
test.use({ trace: "off", screenshot: "off", video: "off" });

const required = process.env.KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const conversationId = process.env.KAREN_HISTORY_CONVERSATION_ID;
const observedRunId = process.env.KAREN_COPILOTKIT_OBSERVED_RUN_ID;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;

type Message = { id: string; role: "user" | "assistant"; content: string };
type ReplayEvent = {
  type: string;
  name?: string;
  value?: unknown;
  messageId?: string;
  threadId?: string;
  runId?: string;
  metadata?: { response_source?: string; replay_only?: boolean };
  messages?: Message[];
};
type Owned = {
  threadId: string;
  messages: Message[];
  replayEvents?: ReplayEvent[];
};

async function signIn(page: import("@playwright/test").Page) {
  if (!email || !password) throw new Error("Live credentials are not configured");
  const configured = process.env.KAREN_BASE_URL;
  if (!configured) throw new Error("Approved CopilotKit deployment URL is required");
  let approved: URL;
  try {
    approved = new URL(configured);
  } catch {
    throw new Error("Approved CopilotKit deployment origin is malformed");
  }
  if (approved.protocol !== "https:" || approved.username || approved.password ||
      approved.port || approved.pathname !== "/" || approved.search || approved.hash) {
    throw new Error("Only an approved clean HTTPS origin can accept credentials");
  }
  await page.goto("/login");
  expect(new URL(page.url()).origin).toBe(approved.origin);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/dashboard(?:[/?#]|$)"), { timeout: 30000 });
  expect(new URL(page.url()).origin).toBe(approved.origin);
}

function parseSse(input: string): ReplayEvent[] {
  const events: ReplayEvent[] = [];
  for (const frame of input.split(/\r?\n\r?\n/)) {
    const dataLines = frame.split(/\r?\n/)
      .filter(line => line.startsWith("data: "))
      .map(line => line.slice("data: ".length));
    if (!dataLines.length) continue;
    const decoded: unknown = JSON.parse(dataLines.join("\n"));
    expect(decoded).toBeTruthy();
    expect(typeof decoded).toBe("object");
    expect(Array.isArray(decoded)).toBe(false);
    events.push(decoded as ReplayEvent);
  }
  return events;
}

function requireAcceptanceFixture() {
  if (required && (!email || !password || !conversationId ||
      !UUID.test(conversationId))) {
    throw new Error(
      "CopilotKit acceptance requires real sanitized sign-in and a persisted conversation UUID",
    );
  }
  test.skip(!email || !password || !conversationId || !UUID.test(conversationId),
    "Requires a real approved authenticated conversation");
}

test("CK-07E2: real CopilotKit connect replays only canonical saved messages and attested CUSTOM events", async ({ page }) => {
  requireAcceptanceFixture();
  if (!conversationId) return;
  await signIn(page);

  const stored = await page.request.get(
    "/api/copilotkit/threads/" + encodeURIComponent(conversationId) + "/messages",
  );
  expect(stored.status(), "Governed history must be available in the deployed runtime")
    .toBe(200);
  expect(stored.headers()["cache-control"]).toContain("no-store");
  const history = await stored.json() as Owned;
  expect(history.threadId).toBe(conversationId);
  expect(Array.isArray(history.messages)).toBe(true);
  expect(history.messages.length).toBeGreaterThan(0);
  expect(history.messages.every(m =>
    Boolean(m.id) && ["user", "assistant"].includes(m.role) &&
    typeof m.content === "string")).toBe(true);

  const connect = await page.request.post("/api/copilotkit/agent/default/connect", {
    data: {
      threadId: conversationId,
      runId: "acceptance_observed_only",
      // The client transcript is untrusted and must not override history.
      messages: [{ id: "untrusted-client-message", role: "assistant",
        content: "Not a saved model answer" }],
      tools: [],
      context: [],
      state: {},
    },
  });
  expect(connect.status()).toBe(200);
  expect(connect.headers()["content-type"]).toContain("text/event-stream");
  expect(connect.headers()["x-karen-response-source"]).toBe("persisted_history");
  const events = parseSse(await connect.text());
  expect(events.length).toBeGreaterThanOrEqual(3);
  expect(events[0].type).toBe("RUN_STARTED");
  expect(events[0].metadata).toEqual({
    response_source: "persisted_history", replay_only: true,
  });
  const snapshot = events[1];
  expect(snapshot.type).toBe("MESSAGES_SNAPSHOT");
  expect(snapshot.messages).toEqual(history.messages);
  const last = events.at(-1);
  expect(last?.type).toBe("RUN_FINISHED");
  expect(last?.metadata).toEqual({
    response_source: "persisted_history", replay_only: true,
  });
  const savedAssistantIds = new Set(history.messages
    .filter(m => m.role === "assistant").map(m => m.id));
  const customs = events.slice(2, -1);
  expect(customs).toEqual(history.replayEvents || []);
  for (const event of customs) {
    expect(event.type).toBe("CUSTOM");
    expect(["karen.presentation.v1", "karen.execution_receipt.v1",
      "karen.response_integrity.v1"]).toContain(event.name);
    expect(event.messageId && savedAssistantIds.has(event.messageId)).toBe(true);
  }
  expect(JSON.stringify(events)).not.toContain("Not a saved model answer");
});

test("CK-07E2: run-event cursor cannot turn missing or interrupted runs into successful model output", async ({ page }) => {
  requireAcceptanceFixture();
  if (!conversationId) return;
  if (required && (!observedRunId || !RUN_ID.test(observedRunId))) {
    throw new Error("Observed run cursor acceptance requires an actual saved run ID");
  }
  test.skip(!observedRunId || !RUN_ID.test(observedRunId),
    "Requires a real journaled run ID; no manufactured cursor fixture");
  if (!observedRunId) return;
  await signIn(page);

  const target = "/api/copilotkit/threads/" + encodeURIComponent(conversationId) +
    "/runs/" + encodeURIComponent(observedRunId) + "/events";
  let after = 0;
  let final = false;
  let completedLedger = false;
  let observedTerminal = false;
  const all: Array<{ seq: number; event: ReplayEvent }> = [];
  for (let pageNo = 0; pageNo < 42; pageNo++) {
    const response = await page.request.get(target + "?after=" + after + "&limit=50");
    expect(response.status(), "Cursor must be enabled and owned").toBe(200);
    expect(response.headers()["cache-control"]).toContain("no-store");
    const data = await response.json() as {
      threadId: string; runId: string; events: Array<{ seq: number; event: ReplayEvent }>;
      nextCursor: number; hasMore: boolean; runStatus: string;
      terminalConfirmed: boolean; journalTerminalObserved: boolean;
      continuationAvailable: boolean; responseSource: string;
    };
    expect(data.threadId).toBe(conversationId);
    expect(data.runId).toBe(observedRunId);
    expect(data.responseSource).toBe("observed_event_journal");
    expect(data.continuationAvailable).toBe(false);
    expect(data.events.length).toBeLessThanOrEqual(50);
    for (const item of data.events) {
      expect(item.seq).toBe(after + 1);
      after = item.seq;
      all.push(item);
    }
    expect(data.nextCursor).toBe(after);
    if (!data.hasMore) {
      final = true;
      completedLedger = data.runStatus === "completed" && data.terminalConfirmed;
      observedTerminal = data.journalTerminalObserved;
      if (!data.terminalConfirmed) {
        expect(all.some(x => x.event.type === "RUN_FINISHED")).toBe(false);
      }
      if (completedLedger && observedTerminal) {
        expect(all.some(x => x.event.type === "RUN_FINISHED")).toBe(true);
      }
      break;
    }
  }
  expect(final, "Event pagination must resolve without a hidden truncation").toBe(true);
  expect(all.length).toBeGreaterThan(0);
  expect(all.length).toBeLessThanOrEqual(2048);
  expect(completedLedger || !observedTerminal ||
    all.some(x => x.event.type === "RUN_ERROR")).toBe(true);
  // Missing run: the server must not resurrect or guess a deleted execution.
  const absent = await page.request.get(
    "/api/copilotkit/threads/" + encodeURIComponent(conversationId) +
    "/runs/nonexistent_acceptance_run/events?after=0&limit=50",
  );
  expect(absent.status()).toBe(404);
});

test("CK-07E2: live page retains the existing chat while consumer replacement is unverified", async ({ page }) => {
  requireAcceptanceFixture();
  await signIn(page);
  await expect(page.getByTestId("persistent-karen-conversation")).toBeVisible();
  // This does not claim CopilotChat is mounted or interactive. A future
  // replacement requires its own real-browser parity and UX acceptance.
  await expect(page.getByTestId("karen-assistant-ui-chat")).toBeVisible();
});
