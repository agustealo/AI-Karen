import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

// Do not mock CopilotRuntime, createCopilotRuntimeHandler, or HttpAgent here.
// This exercises the pinned actual SDK's multi-route discovery contract.
import { GET, POST } from "@/app/api/copilotkit/[[...slug]]/route";

const nativeFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit pinned SDK discovery", () => {
  it("registers Karen's real SDK agent behind current backend authentication", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "http://api:8000/api/auth/me") {
        return Response.json({
          user_id: "user-123",
          tenant_id: "tenant-456",
          is_active: true,
        });
      }
      if (String(input) === "http://api:8000/api/chat/ag-ui/capabilities") {
        return Response.json({ enabled: true });
      }
      throw new Error("Unexpected SDK network destination: " + String(input));
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/info",
      { headers: { cookie: "kari_session=authenticated" } },
    ));

    expect(result.status).toBe(200);
    expect(result.headers.get("content-type")).toContain("application/json");
    const info: unknown = await result.json();
    expect(JSON.stringify(info)).toContain("default");
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "http://api:8000/api/auth/me",
      "http://api:8000/api/chat/ag-ui/capabilities",
    ]);
  });

  it("passes paired model hints through the actual SDK transport to AG-UI", async () => {
    const conversation = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
    const observed: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "http://api:8000/api/auth/me") {
        return Response.json({
          user_id: "user-123",
          tenant_id: "tenant-456",
          is_active: true,
        });
      }
      if (url === "http://api:8000/api/chat/ag-ui/capabilities") {
        return Response.json({ enabled: true });
      }
      if (url === "http://api:8000/api/chat/ag-ui") {
        observed.push(JSON.parse(String(init?.body)) as unknown);
        const stream = [
          { type: "RUN_STARTED", threadId: conversation, runId: "run-model-1" },
          { type: "RUN_FINISHED", threadId: conversation, runId: "run-model-1" },
        ].map((event) => "data: " + JSON.stringify(event) + "\\n\\n").join("");
        return new Response(stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      throw new Error("Unexpected SDK network destination: " + url);
    });
    globalThis.fetch = fetchMock as typeof fetch;
    const response = await POST(new NextRequest(
      "http://localhost:3000/api/copilotkit/agent/default/run", {
        method: "POST",
        headers: {
          cookie: "kari_session=authenticated",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          threadId: conversation,
          runId: "run-model-1",
          messages: [{ id: "message-1", role: "user", content: "Hello" }],
          tools: [],
          context: [],
          state: {},
          forwardedProps: {
            preferred_llm_provider: "local",
            preferred_model: "selected-model",
          },
        }),
      },
    ));
    expect(response.status).toBe(200);
    await response.text();
    expect(observed).toHaveLength(1);
    expect(observed[0]).toMatchObject({
      threadId: conversation,
      forwardedProps: {
        preferred_llm_provider: "local",
        preferred_model: "selected-model",
      },
    });
    // A subsequent automatic-routing run must not inherit the old model hint.
    const automatic = await POST(new NextRequest(
      "http://localhost:3000/api/copilotkit/agent/default/run", {
        method: "POST",
        headers: {
          cookie: "kari_session=authenticated",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          threadId: conversation,
          runId: "run-model-2",
          messages: [{ id: "message-2", role: "user", content: "Route automatically" }],
          tools: [],
          context: [],
          state: {},
        }),
      },
    ));
    expect(automatic.status).toBe(200);
    await automatic.text();
    expect(observed).toHaveLength(2);
    const second = observed[1] as Record<string, unknown>;
    const forwarded = second.forwardedProps as Record<string, unknown> | undefined;
    expect(forwarded?.preferred_llm_provider).toBeUndefined();
    expect(forwarded?.preferred_model).toBeUndefined();

  });

  it("rejects unauthenticated SDK discovery before any runtime work", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;
    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/info",
    ));
    expect(result.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
