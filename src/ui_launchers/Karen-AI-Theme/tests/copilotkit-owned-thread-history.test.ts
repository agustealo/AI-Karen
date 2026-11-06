import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { GET } from "@/app/api/copilotkit/[[...slug]]/route";

const originalFetch = globalThis.fetch;
const THREAD = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const URL = "http://localhost:3000/api/copilotkit/threads/" + THREAD + "/messages";

function request(cookie = "kari_session=user-A", view = ""): NextRequest {
  return new NextRequest(URL + view, {
    headers: { cookie, "x-user-id": "attacker", "x-tenant-id": "foreign" },
  });
}

function reply(
  identity: string,
  messages: unknown[] = [
    { id: "user-1", role: "user", content: "Hello", metadata: { password: "secret" } },
    { id: "assistant-1", role: "assistant", content: "Welcome back", metadata: { internal: "secret" } },
  ],
) {
  return Response.json({
    id: THREAD,
    user_id: identity,
    messages,
    tenant_id: "tenant-A",
    metadata: { authorization: "never-forward" },
  });
}

function guardedBackend(
  conversation: () => Response = () => reply("user-A"),
) {
  const urls: string[] = [];
  const upstream = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    urls.push(url);
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toBe("kari_session=user-A");
    expect(new Headers(init?.headers).has("x-user-id")).toBe(false);
    expect(new Headers(init?.headers).has("x-tenant-id")).toBe(false);
    if (url === "http://api:8000/api/auth/me") {
      return Response.json({ user_id: "user-A", tenant_id: "tenant-A", is_active: true });
    }
    if (url === "http://api:8000/api/chat/ag-ui/capabilities") {
      return Response.json({ enabled: true });
    }
    if (url === "http://api:8000/api/conversations/" + THREAD + "?message_limit=501") return conversation();
    throw new Error("Unexpected external call " + url);
  });
  globalThis.fetch = upstream as typeof fetch;
  return { upstream, urls };
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit owned thread history", () => {
  it("loads ordered owned messages through canonical auth and strips privileged metadata", async () => {
    const { urls } = guardedBackend();
    const response = await GET(request());
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(await response.json()).toEqual({
      threadId: THREAD,
      messages: [
        { id: "user-1", role: "user", content: "Hello" },
        { id: "assistant-1", role: "assistant", content: "Welcome back" },
      ],
    });
    expect(urls).toEqual([
      "http://api:8000/api/auth/me",
      "http://api:8000/api/chat/ag-ui/capabilities",
      "http://api:8000/api/conversations/" + THREAD + "?message_limit=501",
    ]);
  });

  it("replays 500 canonical plaintext messages without accidentally fetching the legacy 100-message page", async () => {
    guardedBackend(() => reply("user-A", Array.from({ length: 500 }, (_, index) => ({
      id: "message-" + index,
      role: index % 2 === 0 ? "user" : "assistant",
      content: "turn " + index,
    }))));
    const response = await GET(request());
    expect(response.status).toBe(200);
    const snapshot = await response.json();
    expect(snapshot.messages).toHaveLength(500);
    expect(snapshot.messages[0].id).toBe("message-0");
    expect(snapshot.messages[499].id).toBe("message-499");
  });

  it("does not disclose a foreign user's conversation even if upstream accidentally returns one", async () => {
    guardedBackend(() => reply("foreign-user"));
    const result = await GET(request());
    expect(result.status).toBe(404);
    expect(JSON.stringify(await result.json())).not.toContain("Welcome back");
  });

  it("returns the same 404 for absent and forbidden owned snapshots", async () => {
    for (const code of [401, 403, 404]) {
      guardedBackend(() => Response.json({ detail: "private account info" }, { status: code }));
      const result = await GET(request());
      expect(result.status).toBe(404);
      expect(JSON.stringify(await result.json())).not.toContain("private account info");
    }
  });

  it("rejects malformed, oversized, or mismatched history without partial disclosure", async () => {
    const cases: Array<() => Response> = [
      () => Response.json({ id: "another-uuid", user_id: "user-A", messages: [] }),
      () => Response.json({ id: THREAD, user_id: "user-A", messages: null }),
      () => reply("user-A", [{ id: "", role: "assistant", content: "private" }]),
      () => reply("user-A", Array.from({ length: 501 }, (_, index) =>
        ({ id: String(index), role: "user", content: "hello" }))),
      () => new Response("not json", { headers: { "content-type": "application/json" } }),
      () => new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new Uint8Array(1024 * 1024));
          controller.enqueue(new Uint8Array(1024 * 1024 + 1));
          controller.close();
        },
      }), { headers: { "content-type": "application/json" } }),
      () => new Response("oversized", {
        headers: { "content-type": "application/json", "content-length": "2097153" },
      }),
    ];
    for (const [index, responseOf] of cases.entries()) {
      guardedBackend(responseOf);
      const result = await GET(request());
      // A foreign/mismatched thread must be indistinguishable from missing.
      expect(result.status).toBe(index === 0 ? 404 : 502);
      expect(JSON.stringify(await result.json())).not.toContain("private");
    }
  });

  it("refuses text-only hydration when canonical history contains tool or presentation state", async () => {
    const richMessages: unknown[][] = [
      [
        { id: "user-1", role: "user", content: "Weather?" },
        { id: "assistant-1", role: "assistant", content: "Sunny",
          structured_content: { schema_version: 1, type: "weather.observation" } },
      ],
      [
        { id: "user-1", role: "user", content: "Execute research" },
        { id: "tool-1", role: "tool", content: "Sensitive tool output" },
      ],
      [
        { id: "system-1", role: "system", content: "System-level data" },
      ],
      [
        { id: "assistant-1", role: "assistant", content: "Done",
          metadata: { execution_receipt: { response_source: "model" } } },
      ],
      [
        { id: "assistant-2", role: "assistant", content: "Model answer",
          metadata: {
            actual_provider: "local",
            actual_model: "sample-model",
            response_source: "model",
          } },
      ],
      [
        { id: "assistant-1", role: "assistant", content: "Done",
          attachments: [{ name: "document.pdf" }] },
      ],
    ];
    for (const messages of richMessages) {
      guardedBackend(() => reply("user-A", messages));
      const result = await GET(request());
      expect(result.status).toBe(409);
      const body = JSON.stringify(await result.json());
      expect(body).toContain("not yet supported");
      expect(body).not.toContain("Sensitive tool output");
      expect(body).not.toContain("weather.observation");
    }
  });

  it("recovers authenticated rich conversations as read-only text without capability discovery", async () => {
    const { urls } = guardedBackend(() => reply("user-A", [
      { id: "user-1", role: "user", content: "What is happening?" },
      { id: "tool-1", role: "tool", content: "private result with a token" },
      { id: "assistant-1", role: "assistant", content: "Here is the report",
        attachments: [{ file: "confidential.pdf" }],
        metadata: {
          structured_content: { component_type: "future.news.card" },
          actual_provider: "local", actual_model: "verified-model",
          api_key: "private-provider-secret",
        } },
    ]));
    const result = await GET(request("kari_session=user-A", "?view=transcript"));
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toContain("no-store");
    const body = await result.json();
    expect(body).toEqual({
      threadId: THREAD, read_only: true, text_only: true, omitted_entries: 1,
      messages: [
        { id: "user-1", role: "user", content: "What is happening?" },
        { id: "assistant-1", role: "assistant", content: "Here is the report" },
      ],
    });
    const raw = JSON.stringify(body);
    for (const secret of ["private result", "private-provider-secret", "confidential.pdf", "future.news.card"]) {
      expect(raw).not.toContain(secret);
    }
    expect(urls).toEqual([
      "http://api:8000/api/auth/me",
      "http://api:8000/api/conversations/" + THREAD + "?message_limit=501",
    ]);
  });

  it("keeps read-only recovery subject to owner and strict message validation", async () => {
    guardedBackend(() => reply("foreign-user", [
      { id: "a1", role: "assistant", content: "Private answer" },
    ]));
    const foreign = await GET(request("kari_session=user-A", "?view=transcript"));
    expect(foreign.status).toBe(404);
    expect(JSON.stringify(await foreign.json())).not.toContain("Private answer");

    guardedBackend(() => reply("user-A", [
      { id: "same", role: "user", content: "First" },
      { id: "same", role: "assistant", content: "Second" },
    ]));
    const duplicate = await GET(request("kari_session=user-A", "?view=transcript"));
    expect(duplicate.status).toBe(502);
    expect(JSON.stringify(await duplicate.json())).not.toContain("Second");

    guardedBackend(() => reply("user-A", [
      { id: "m1", role: "assistant", content: "Known" },
      { id: "rogue", role: "unexpected", content: "untrusted" },
    ]));
    const untrusted = await GET(request("kari_session=user-A", "?view=transcript"));
    expect(untrusted.status).toBe(502);
    expect(JSON.stringify(await untrusted.json())).not.toContain("untrusted");
  });

  it("does not allow arbitrary transcript modes, query overrides or anonymous recovery", async () => {
    const { urls } = guardedBackend();
    for (const suffix of [
      "?view=full", "?view=transcript&admin=true", "?view=transcript&view=transcript",
    ]) {
      const result = await GET(request("kari_session=user-A", suffix));
      expect(result.status).toBe(400);
    }
    expect(urls.every(url => !url.includes("/api/conversations/"))).toBe(true);

    const calls = vi.fn();
    globalThis.fetch = calls as typeof fetch;
    const anonymous = await GET(request("", "?view=transcript"));
    expect(anonymous.status).toBe(401);
    expect(calls).not.toHaveBeenCalled();
  });

  it("rejects anonymous history before contacting the backend", async () => {
    const upstream = vi.fn();
    globalThis.fetch = upstream as typeof fetch;
    const response = await GET(new NextRequest(URL));
    expect(response.status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("keeps unscoped list, events, state, and connect routes denied", async () => {
    const upstream = vi.fn();
    globalThis.fetch = upstream as typeof fetch;
    for (const path of [
      "/api/copilotkit/threads",
      "/api/copilotkit/threads/" + THREAD + "/events",
      "/api/copilotkit/threads/" + THREAD + "/state",
    ]) {
      const method = path.endsWith("/connect") ? "POST" : "GET";
      const candidate = new NextRequest("http://localhost:3000" + path, {
        method, headers: { cookie: "kari_session=user-A" },
      });
      const response = method === "GET" ? await GET(candidate) : await (await import(
        "@/app/api/copilotkit/[[...slug]]/route"
      )).POST(candidate);
      expect(response.status, path).toBe(404);
    }
    expect(upstream).not.toHaveBeenCalled();
  });
});
