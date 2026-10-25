import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

// Real CopilotKit v2 handler + HttpAgent. Only the external Karen backend is
// simulated; never treat this as proof that a live model/database is working.
import { POST } from "@/app/api/copilotkit/[[...slug]]/route";

const nativeFetch = globalThis.fetch;
const CONVERSATION = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const RUN_ID = "run_123";
const AGENT_ENDPOINT = "http://api:8000/api/chat/ag-ui";
const AUTH_ENDPOINT = "http://api:8000/api/auth/me";
const CAPABILITIES_ENDPOINT = "http://api:8000/api/chat/ag-ui/capabilities";

function sdkRun(overrides: Record<string, unknown> = {}): NextRequest {
  return new NextRequest("http://localhost:3000/api/copilotkit/agent/default/run", {
    method: "POST",
    headers: {
      cookie: "kari_session=verified",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      threadId: CONVERSATION,
      runId: RUN_ID,
      messages: [{ id: "user_1", role: "user", content: "Check Karen" }],
      tools: [],
      context: [],
      state: {},
      forwardedProps: {},
      ...overrides,
    }),
  });
}

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit v2 run over canonical Karen AG-UI", () => {
  it("streams a full AG-UI run without a second model executor", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const reply = [
      { type: "RUN_STARTED", threadId: CONVERSATION, runId: RUN_ID },
      { type: "TEXT_MESSAGE_START", messageId: "assistant_1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "assistant_1", delta: "Karen test execution" },
      { type: "TEXT_MESSAGE_END", messageId: "assistant_1" },
      { type: "RUN_FINISHED", threadId: CONVERSATION, runId: RUN_ID },
    ].map((event) => "data: " + JSON.stringify(event) + "\n\n").join("");

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === AUTH_ENDPOINT) {
        return Response.json({
          user_id: "user-123",
          tenant_id: "tenant-456",
          is_active: true,
        });
      }
      if (url === CAPABILITIES_ENDPOINT) {
        expect(init?.redirect).toBe("manual");
        expect(new Headers(init?.headers).get("cookie")).toBe("kari_session=verified");
        return Response.json({ enabled: true });
      }
      if (url === AGENT_ENDPOINT) {
        expect(init?.redirect).toBe("manual");
        const headers = new Headers(init?.headers);
        expect(headers.get("cookie")).toBe("kari_session=verified");
        expect(headers.has("x-tenant-id")).toBe(false);
        expect(headers.has("x-user-id")).toBe(false);
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>;
        expect(payload.threadId).toBe(CONVERSATION);
        expect(payload.runId).toBe(RUN_ID);
        return new Response(reply, {
          headers: { "content-type": "text/event-stream" },
        });
      }
      throw new Error("Unexpected outbound request: " + url);
    }) as typeof fetch;

    const response = await POST(sdkRun());
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    const stream = await response.text();
    expect(stream).toContain("RUN_STARTED");
    expect(stream).toContain("Karen test execution");
    expect(stream).toContain("RUN_FINISHED");
    expect(calls.map((call) => call.url)).toEqual([AUTH_ENDPOINT, CAPABILITIES_ENDPOINT, AGENT_ENDPOINT]);
  });

  it("rejects a client-provided privileged tool without invoking Karen", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;
    const response = await POST(sdkRun({ tools: [{ name: "unapproved_write" }] }));
    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
