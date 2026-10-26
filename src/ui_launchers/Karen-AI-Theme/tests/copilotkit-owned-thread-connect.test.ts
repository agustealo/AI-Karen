import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { POST } from "@/app/api/copilotkit/[[...slug]]/route";

const originalFetch = globalThis.fetch;
const THREAD = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const ENDPOINT = "http://localhost:3000/api/copilotkit/agent/default/connect";
const AUTH = "http://api:8000/api/auth/me";
const FLAGS = "http://api:8000/api/chat/ag-ui/capabilities";
const HISTORY = "http://api:8000/api/conversations/" + THREAD;

function connect(payload: unknown = { threadId: THREAD }) {
  return new NextRequest(ENDPOINT, {
    method: "POST",
    headers: {
      cookie: "kari_session=owner",
      "content-type": "application/json",
      "x-tenant-id": "forged-foreign",
      "x-user-id": "imposter",
    },
    body: JSON.stringify(payload),
  });
}

function ownerHistory(messages: unknown[] = [
  { id: "m1", role: "user", content: "Hello" },
  { id: "m2", role: "assistant", content: "Previously saved answer" },
]) {
  return Response.json({
    id: THREAD,
    user_id: "user-owner",
    tenant_id: "tenant-A",
    messages,
    metadata: { private: "never release" },
  });
}

function mockBackend(history: () => Response = () => ownerHistory()) {
  const destinations: string[] = [];
  globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const target = String(url);
    destinations.push(target);
    expect(init?.redirect).toBe("manual");
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("kari_session=owner");
    expect(headers.has("x-user-id")).toBe(false);
    expect(headers.has("x-tenant-id")).toBe(false);
    if (target === AUTH) {
      return Response.json({
        user_id: "user-owner",
        tenant_id: "tenant-A",
        is_active: true,
      });
    }
    if (target === FLAGS) return Response.json({ enabled: true });
    if (target === HISTORY) return history();
    throw new Error("Unexpected destination: " + target);
  }) as typeof fetch;
  return destinations;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit completed-history reconnect", () => {
  it("replays only owned persisted text as AG-UI snapshots, never a new provider run", async () => {
    const destinations = mockBackend();
    const response = await POST(connect());
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(response.headers.get("x-karen-response-source")).toBe("persisted_history");
    expect(response.headers.get("cache-control")).toContain("no-store");
    const stream = await response.text();
    const events = stream.split("\n").filter((line) => line.startsWith("data: "))
      .map((line) => JSON.parse(line.slice(6)) as Record<string, unknown>);
    expect(events.map((e) => e.type)).toEqual([
      "RUN_STARTED", "MESSAGES_SNAPSHOT", "RUN_FINISHED",
    ]);
    expect(events[0].threadId).toBe(THREAD);
    expect(events[0].runId).toMatch(/^history_/);
    expect(events[0].metadata).toEqual({
      response_source: "persisted_history", replay_only: true,
    });
    expect(events[1].messages).toEqual([
      { id: "m1", role: "user", content: "Hello" },
      { id: "m2", role: "assistant", content: "Previously saved answer" },
    ]);
    expect(events[2].runId).toBe(events[0].runId);
    expect(stream).not.toContain("never release");
    expect(destinations).toEqual([AUTH, FLAGS, HISTORY]);
    expect(destinations).not.toContain("http://api:8000/api/chat/ag-ui");
  });

  it("does not replay another user's thread, even if upstream returns it", async () => {
    mockBackend(() => Response.json({
      id: THREAD, user_id: "another-user",
      messages: [{ id: "private", role: "assistant", content: "Secret answer" }],
    }));
    const response = await POST(connect());
    expect(response.status).toBe(404);
    expect(JSON.stringify(await response.json())).not.toContain("Secret answer");
  });

  it("does not replay unverified rich/tool history or emit a success stream", async () => {
    mockBackend(() => ownerHistory([
      { id: "assistant-1", role: "assistant", content: "Report",
        structured_content: { presentation: { component_type: "weather.observation" } } },
    ]));
    const response = await POST(connect());
    expect(response.status).toBe(409);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(JSON.stringify(await response.json())).not.toContain("weather.observation");
  });

  it("refuses client-controlled tool, context, state and arbitrary endpoint fields", async () => {
    for (const payload of [
      { threadId: "not-a-uuid" },
      { threadId: THREAD, tools: [{ name: "unapproved_write" }] },
      { threadId: THREAD, state: { role: "admin" } },
      { threadId: THREAD, context: [{ privileged: true }] },
      { threadId: THREAD, runId: "invalid id with whitespace" },
    ]) {
      mockBackend();
      const response = await POST(connect(payload));
      expect(response.status).toBe(422);
      expect(response.headers.get("content-type")).toContain("application/json");
    }
  });

  it("fails closed when backend transport is disabled without accessing history", async () => {
    const destinations: string[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
      const target = String(url);
      destinations.push(target);
      return target === AUTH
        ? Response.json({ user_id: "user-owner", tenant_id: "tenant-A", is_active: true })
        : Response.json({ enabled: false });
    }) as typeof fetch;
    const response = await POST(connect());
    expect(response.status).toBe(503);
    expect(destinations).toEqual([AUTH, FLAGS]);
  });

  it("rejects anonymous reconnect before contacting canonical services", async () => {
    const upstream = vi.fn();
    globalThis.fetch = upstream as typeof fetch;
    const response = await POST(new NextRequest(ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ threadId: THREAD }),
    }));
    expect(response.status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });
});
