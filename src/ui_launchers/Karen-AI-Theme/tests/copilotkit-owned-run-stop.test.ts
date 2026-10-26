import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { POST } from "@/app/api/copilotkit/[[...slug]]/route";

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
      const upstream = vi.fn();
      globalThis.fetch = upstream as typeof fetch;
      const response = await POST(stop(payload));
      expect(response.status, JSON.stringify(payload)).toBe(422);
      // Explicit stop envelope validation happens after session/capability check.
      // This may hit auth/capabilities in the future; never the actual stop endpoint.
      expect(upstream.mock.calls.some(([url]) => String(url).includes("/cancel"))).toBe(false);
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
