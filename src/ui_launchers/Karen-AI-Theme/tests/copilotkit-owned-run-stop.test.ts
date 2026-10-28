import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { GET, POST } from "@/app/api/copilotkit/[[...slug]]/route";

const originalFetch = globalThis.fetch;
const THREAD = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const SDK_STOP = "http://localhost:3000/api/copilotkit/agent/default/stop/" + THREAD;
const BACKEND_STOP = "http://api:8000/api/chat/ag-ui/runs/" + THREAD + "/run-exact/cancel";
const AUTH = "http://api:8000/api/auth/me";
const FLAGS = "http://api:8000/api/chat/ag-ui/capabilities";

function stop(body: unknown = { runId: "run-exact" }, cookie = "kari_session=owner") {
  return new NextRequest(SDK_STOP, {
    method: "POST",
    headers: {
      cookie,
      "content-type": "application/json",
      "x-user-id": "forged-user",
      "x-tenant-id": "foreign-tenant",
    },
    body: JSON.stringify(body),
  });
}

function backend(
  result: () => Response = () => Response.json({
    status: "cancelling",
    cancel_requested: true,
    cancellation_confirmed: false,
  }, { status: 202 }),
) {
  const seen: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    seen.push(url);
    expect(init?.redirect).toBe("manual");
    expect(init?.cache).toBe("no-store");
    expect(new Headers(init?.headers).get("cookie")).toBe("kari_session=owner");
    expect(new Headers(init?.headers).has("x-user-id")).toBe(false);
    expect(new Headers(init?.headers).has("x-tenant-id")).toBe(false);
    if (url === AUTH) {
      return Response.json({
        user_id: "user-owner", tenant_id: "tenant-A", is_active: true,
      });
    }
    if (url === FLAGS) return Response.json({ enabled: true });
    if (url === BACKEND_STOP) {
      expect(init?.method).toBe("POST");
      expect(init?.body).toBeUndefined();
      return result();
    }
    throw new Error("Unexpected request: " + url);
  }) as typeof fetch;
  return seen;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit v2 exact-run stop uses only Karen runtime", () => {
  it("accepts stop intent, without claiming the worker has cancelled", async () => {
    const seen = backend();
    const response = await POST(stop());
    expect(response.status).toBe(202);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(await response.json()).toEqual({
      status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
    });
    expect(seen).toEqual([AUTH, FLAGS, BACKEND_STOP]);
  });

  it("returns confirmed cancelled only from a canonical 200 terminal receipt", async () => {
    backend(() => Response.json({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    }));
    const response = await POST(stop());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    });
  });

  it("does not report completed, failed or expired runs as successfully stopped", async () => {
    backend(() => Response.json({ detail: "already complete" }, { status: 409 }));
    const response = await POST(stop());
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toContain("cancelled");
  });

  it("does not disclose another user's or missing run", async () => {
    backend(() => Response.json({ detail: "private foreign run" }, { status: 403 }));
    const response = await POST(stop());
    expect(response.status).toBe(404);
    expect(JSON.stringify(await response.json())).not.toContain("private");
  });

  it("refuses run-less or forged SDK cancellation before reaching any backend", async () => {
    for (const payload of [
      {},
      { threadId: THREAD },
      { runId: "" },
      { runId: "wrong run id" },
      { runId: "run-exact", tools: [{ name: "privileged" }] },
      { runId: "run-exact", state: { role: "admin" } },
      { runId: "run-exact", user_id: "foreign" },
    ]) {
      const seen = backend();
      const response = await POST(stop(payload));
      expect(response.status, JSON.stringify(payload)).toBe(422);
      // Authentication and capability discovery are allowed, not execution.
      expect(seen).toEqual([AUTH, FLAGS]);
    }
  });

  it("does not accept a stop without JSON content type", async () => {
    const upstream = vi.fn();
    globalThis.fetch = upstream as typeof fetch;
    const response = await POST(new NextRequest(SDK_STOP, {
      method: "POST", headers: { cookie: "kari_session=owner" },
    }));
    expect(response.status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("refuses invented backend confirmation and redirects", async () => {
    for (const forged of [
      Response.json({ status: "cancelled" }),
      Response.json({ status: "cancelled", cancellation_confirmed: true }, { status: 202 }),
      new Response(null, { status: 307, headers: { location: "https://bad.test/" } }),
    ]) {
      backend(() => forged);
      const response = await POST(stop());
      expect(response.status).toBe(503);
    }
  });

  it("rejects oversized stop payloads before dispatching a model or cancellation", async () => {
    const seen = backend();
    const oversized = stop({ runId: "run-exact", extra: "x".repeat(4096) });
    const response = await POST(oversized);
    expect(response.status).toBe(413);
    expect(seen).toEqual([AUTH, FLAGS]);
  });

  it("rejects oversized backend receipts without buffering a full response", async () => {
    const seen = backend(() => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(4096));
        controller.enqueue(new Uint8Array(1));
        controller.close();
      },
    }), { status: 202, headers: { "content-type": "application/json" } }));
    const response = await POST(stop());
    expect(response.status).toBe(503);
    expect(seen).toEqual([AUTH, FLAGS, BACKEND_STOP]);
  });

  it("fails closed when canonical transport is disabled or auth is missing", async () => {
    const urls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      return url === AUTH
        ? Response.json({ user_id: "user-owner", tenant_id: "tenant-A", is_active: true })
        : Response.json({ enabled: false });
    }) as typeof fetch;
    expect((await POST(stop())).status).toBe(503);
    expect(urls).toEqual([AUTH, FLAGS]);

    const none = vi.fn();
    globalThis.fetch = none as typeof fetch;
    const noAuth = new NextRequest(SDK_STOP, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ runId: "run-exact" }),
    });
    expect((await POST(noAuth)).status).toBe(401);
    expect(none).not.toHaveBeenCalled();
  });
});

describe("CopilotKit v2 canonical read-only run status", () => {
  const statusUrl = "http://localhost:3000/api/copilotkit/agent/default/runs/" +
    THREAD + "/run-exact/status";
  const upstreamUrl = "http://api:8000/api/chat/ag-ui/runs/" +
    THREAD + "/run-exact/status";

  function read(cookie = "kari_session=owner") {
    return new NextRequest(statusUrl, {
      method: "GET",
      headers: { cookie, "x-user-id": "forged-owner", "x-tenant-id": "forged-tenant" },
    });
  }

  function mockStatus(result: () => Response) {
    const seen: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      seen.push(url);
      expect(init?.cache).toBe("no-store");
      expect(init?.redirect).toBe("manual");
      expect(new Headers(init?.headers).has("x-user-id")).toBe(false);
      expect(new Headers(init?.headers).has("x-tenant-id")).toBe(false);
      if (url === AUTH) return Response.json({
        user_id: "user-owner", tenant_id: "tenant-A", is_active: true,
      });
      if (url === FLAGS) return Response.json({
        enabled: true, governed_history: true,
      });
      if (url === upstreamUrl) {
        expect(init?.method).toBe("GET");
        expect(init?.body).toBeUndefined();
        return result();
      }
      throw new Error("Unexpected request: " + url);
    }) as typeof fetch;
    return seen;
  }

  it("reports a pending stop without inventing confirmation or mutation", async () => {
    const seen = mockStatus(() => Response.json({
      status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
    }));
    const response = await GET(read());
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(await response.json()).toEqual({
      status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
    });
    expect(seen).toEqual([AUTH, FLAGS, upstreamUrl]);
  });

  it("only reports confirmed cancellation from the backend's complete evidence", async () => {
    mockStatus(() => Response.json({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
      private_tenant_token: "never-forward",
    }));
    const response = await GET(read());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    });
  });

  it("fails closed on malformed confirmation, redirect, missing run and disabled durability", async () => {
    for (const invalid of [
      Response.json({ status: "completed", cancel_requested: false,
        cancellation_confirmed: true }),
      Response.json({ status: "cancelled", cancel_requested: false,
        cancellation_confirmed: true }),
      new Response(null, { status: 307, headers: { location: "https://forged.test" } }),
    ]) {
      mockStatus(() => invalid);
      const response = await GET(read());
      expect(response.status).toBe(503);
      expect(JSON.stringify(await response.json())).not.toContain("confirmed");
    }
    mockStatus(() => Response.json({ detail: "private foreign user" }, { status: 403 }));
    const foreign = await GET(read());
    expect(foreign.status).toBe(404);
    expect(JSON.stringify(await foreign.json())).not.toContain("private");
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === AUTH) return Response.json({
        user_id: "user-owner", tenant_id: "tenant-A", is_active: true,
      });
      if (url === FLAGS) return Response.json({
        enabled: true, governed_history: false,
      });
      throw new Error("Disabled durability must not reach a run");
    }) as typeof fetch;
    expect((await GET(read())).status).toBe(404);
  });

  it("does not let a runless or invalid thread status reach backend", async () => {
    const spy = vi.fn();
    globalThis.fetch = spy as typeof fetch;
    const invalid = new NextRequest(
      "http://localhost:3000/api/copilotkit/agent/default/runs/" +
      THREAD + "/invalid%20run/status",
    );
    expect((await GET(invalid)).status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });
});
