import { afterEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  proxy: vi.fn(),
}));

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  proxyToBackend: backend.proxy,
}));

import { GET } from "@/app/api/health/route";

const request = () => new Request("https://approved.example/api/health", {
  method: "GET",
});

const canonicalReady = {
  ready: true,
  status: "ready",
  components: { configuration: "ready", database: "ready" },
};

function upstream(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  backend.proxy.mockReset();
  vi.restoreAllMocks();
});

describe("live canonical backend readiness", () => {
  it("accepts only explicit canonical database and configuration readiness", async () => {
    backend.proxy.mockResolvedValue(upstream(canonicalReady));
    const result = await GET(request());
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "ok", backend_ready: true });
    expect(backend.proxy).toHaveBeenCalledTimes(1);
    expect(backend.proxy.mock.calls[0][1]).toBe("/ready");
    expect(backend.proxy.mock.calls[0][2]).toEqual({ followRedirects: false });
  });

  it.each([
    [{ ready: false, status: "not_ready", components: { configuration: "ready", database: "unavailable" } }],
    [{ ready: true, status: "degraded", components: { configuration: "ready", database: "ready" } }],
    [{ ready: true, status: "ready", components: { configuration: "ready", database: "unavailable" } }],
    [{ ready: true, status: "ready", components: { configuration: "unavailable", database: "ready" } }],
    [{ ready: true, status: "ready" }],
    [{ status: "healthy", services: {}, nlp_assets: {} }],
    [null],
    ["healthy"],
  ])("does not invent consumer readiness from an unverified HTTP 200 payload (%j)", async (payload) => {
    backend.proxy.mockResolvedValue(upstream(payload));
    const result = await GET(request());
    expect(result.status).toBe(503);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "initializing", backend_ready: false });
  });

  it.each([401, 403, 404, 429, 500, 502, 504])(
    "normalizes upstream HTTP %i to a private, uncached 503 readiness failure",
    async (status) => {
      backend.proxy.mockResolvedValue(new Response(
        JSON.stringify({
          error_code: "BACKEND_UPSTREAM_UNAVAILABLE",
          detail: "Private internal endpoint and credential are not public",
        }),
        {
          status,
          headers: {
            "content-type": "application/json",
            "x-internal-backend-address": "private.internal",
          },
        },
      ));
      const result = await GET(request());
      expect(result.status).toBe(503);
      expect(result.headers.get("cache-control")).toBe("no-store");
      expect(result.headers.get("x-internal-backend-address")).toBeNull();
      expect(await result.json()).toEqual({
        status: "initializing",
        backend_ready: false,
      });
      expect(backend.proxy).toHaveBeenCalledTimes(1);
    },
  );

  it("never exposes an upstream error page or a redirect as readiness evidence", async () => {
    backend.proxy.mockResolvedValueOnce(new Response("<private>secret</private>", {
      status: 502,
      headers: { "content-type": "text/html" },
    })).mockResolvedValueOnce(new Response(null, {
      status: 302,
      headers: { location: "https://internal.example/private" },
    }));

    for (const expected of [502, 302]) {
      const result = await GET(request());
      expect(result.status).toBe(503);
      expect(result.headers.get("location")).toBeNull();
      expect(await result.json()).toEqual({
        status: "initializing",
        backend_ready: false,
      });
      expect(result.headers.get("cache-control")).toBe("no-store");
      expect(backend.proxy).toHaveBeenCalledTimes(expected === 502 ? 1 : 2);
    }
  });

  it("fails closed on canonical backend 503 without leaking service diagnostics", async () => {
    backend.proxy.mockResolvedValue(upstream({
      detail: { status: "not_ready", components: { database: "unavailable" } },
    }, 503));
    const result = await GET(request());
    expect(result.status).toBe(503);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "initializing", backend_ready: false });
  });

  it("rejects invalid JSON from an upstream that incorrectly reports 200", async () => {
    backend.proxy.mockResolvedValue(new Response("<html>gateway</html>", {
      status: 200,
      headers: { "content-type": "text/html" },
    }));
    const result = await GET(request());
    expect(result.status).toBe(503);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "initializing", backend_ready: false });
  });

  it("does not cache or disguise a thrown upstream transport error", async () => {
    backend.proxy.mockRejectedValue(new Error("backend unavailable"));
    const result = await GET(request());
    expect(result.status).toBe(503);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "initializing", backend_ready: false });
  });
});
