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

afterEach(() => {
  backend.proxy.mockReset();
  vi.restoreAllMocks();
});

describe("live canonical backend readiness", () => {
  it("returns a non-cacheable ready response only when the canonical backend responds 200", async () => {
    backend.proxy.mockResolvedValue(new Response(
      JSON.stringify({ status: "ok" }),
      { status: 200, headers: { "content-type": "application/json" } },
    ));
    const result = await GET(request());
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ status: "ok", backend_ready: true });
    expect(backend.proxy).toHaveBeenCalledTimes(1);
    expect(backend.proxy.mock.calls[0][1]).toBe("/api/health");
  });

  it("never turns a backend 502 into a successful frontend readiness receipt", async () => {
    backend.proxy.mockResolvedValue(new Response(
      JSON.stringify({ detail: "Failed to proxy /api/health to backend", error: "fetch failed" }),
      { status: 502, headers: { "content-type": "application/json", "cache-control": "no-store" } },
    ));
    const result = await GET(request());
    expect(result.status).toBe(502);
    expect(await result.json()).toEqual({
      detail: "Failed to proxy /api/health to backend",
      error: "fetch failed",
    });
  });

  it("does not cache readiness if the proxy itself fails", async () => {
    backend.proxy.mockRejectedValue(new Error("backend unavailable"));
    const result = await GET(request());
    expect(result.status).toBe(503);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toMatchObject({
      status: "initializing",
      backend_ready: false,
    });
  });
});
