import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const sdk = vi.hoisted(() => ({
  agents: [] as Array<{ url: string; headers: Record<string, string>; fetch: typeof fetch }>,
  handlers: 0,
}));

vi.mock("@ag-ui/client-v1", () => ({
  HttpAgent: class {
    constructor(config: { url: string; headers: Record<string, string>; fetch: typeof fetch }) {
      sdk.agents.push(config);
    }
  },
}));

vi.mock("@copilotkit/runtime/v2", () => ({
  CopilotRuntime: class {
    constructor(_config: unknown) {}
  },
  createCopilotRuntimeHandler: () => {
    sdk.handlers += 1;
    return async () => new Response("SDK accepted", { status: 200 });
  },
}));

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { GET, POST, verifyKarenCopilotSession } from
  "@/app/api/copilotkit/[[...slug]]/route";

const ORIGINAL_FETCH = globalThis.fetch;

function request(headers: Record<string, string> = {}): NextRequest {
  return new NextRequest("http://localhost:3000/api/copilotkit/info", { headers });
}

function authenticatedReply(
  overrides: Record<string, unknown> = {},
): Response {
  return Response.json({
    user_id: "user-A",
    tenant_id: "tenant-A",
    is_active: true,
    ...overrides,
  });
}

describe("CopilotKit v2 protected gateway", () => {
  beforeEach(() => {
    sdk.agents.length = 0;
    sdk.handlers = 0;
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it("denies anonymous discovery before creating an SDK runtime", async () => {
    const upstream = vi.fn();
    globalThis.fetch = upstream as typeof fetch;
    const response = await GET(request());
    expect(response.status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
    expect(sdk.handlers).toBe(0);
  });

  it("uses canonical auth and refuses forged tenant headers", async () => {
    const upstream = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => authenticatedReply());
    globalThis.fetch = upstream as typeof fetch;
    const response = await POST(request({
      cookie: "kari_session=valid",
      "x-user-id": "attacker",
      "x-tenant-id": "foreign",
      "x-api-key": "untrusted",
    }));
    expect(response.status).toBe(200);
    expect(sdk.agents).toHaveLength(1);
    expect(sdk.agents[0].url).toBe("http://api:8000/api/chat/ag-ui");
    expect(sdk.agents[0].headers).toEqual({ Cookie: "kari_session=valid" });
    const authInit = upstream.mock.calls[0][1] as RequestInit;
    expect(authInit.redirect).toBe("manual");
    expect((authInit.headers as Record<string, string>)["x-tenant-id"]).toBeUndefined();
  });

  it("fails closed on invalid principal and does not activate an agent", async () => {
    globalThis.fetch = vi.fn(async () =>
      authenticatedReply({ tenant_id: "default" })) as typeof fetch;
    expect((await GET(request({ authorization: "Bearer invalid" }))).status).toBe(401);
    expect(sdk.handlers).toBe(0);
  });

  it("reports canonical auth outage without claiming an agent ran", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("unavailable");
    }) as typeof fetch;
    expect((await GET(request({ cookie: "kari_session=x" }))).status).toBe(503);
    expect(sdk.handlers).toBe(0);
  });

  it("does not follow redirect responses from authentication", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(null, { status: 307, headers: { location: "https://evil.example/receive" } })
    ) as typeof fetch;
    expect((await GET(request({ cookie: "kari_session=x" }))).status).toBe(503);
    expect(sdk.handlers).toBe(0);
  });

  it("uses a new per-request agent and prevents transcript redirects", async () => {
    globalThis.fetch = vi.fn(async () => authenticatedReply()) as typeof fetch;
    expect((await GET(request({ cookie: "kari_session=one" }))).status).toBe(200);
    expect((await GET(request({ cookie: "kari_session=two" }))).status).toBe(200);
    expect(sdk.agents).toHaveLength(2);
    expect(sdk.agents[0]).not.toBe(sdk.agents[1]);
    expect(sdk.agents[0].headers.Cookie).toBe("kari_session=one");
    expect(sdk.agents[1].headers.Cookie).toBe("kari_session=two");
    await sdk.agents[0].fetch("http://api:8000/api/chat/ag-ui", {
      method: "POST",
      body: "{}",
    });
    const allCalls = vi.mocked(globalThis.fetch).mock.calls;
    expect((allCalls.at(-1)?.[1] as RequestInit).redirect).toBe("manual");
  });

  it("exposes session validation without trusting browser-provided identity", async () => {
    globalThis.fetch = vi.fn(async () => authenticatedReply()) as typeof fetch;
    const validated = await verifyKarenCopilotSession(
      request({ cookie: "kari_session=good", "x-user-id": "impersonated" }),
      "http://api:8000",
    );
    expect(validated).not.toBeInstanceOf(Response);
    if (validated instanceof Response) throw new Error("Auth was unexpectedly denied");
    expect(validated.principal.user_id).toBe("user-A");
    expect(validated.principal.tenant_id).toBe("tenant-A");
  });
});
