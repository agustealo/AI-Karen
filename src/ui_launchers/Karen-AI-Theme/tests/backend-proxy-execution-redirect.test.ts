import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { proxyToBackend } from "@/app/api/_lib/backend-proxy";

const originalFetch = globalThis.fetch;

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("Canonical backend proxy execution redirects", () => {
  it("does not repeat a GET after the canonical proxy deadline expires", async () => {
    vi.useFakeTimers();
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Timed out", "AbortError"));
        }, { once: true });
      }),
    );
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/auth/first-run");
    const resultPromise = proxyToBackend(request, "/api/auth/first-run", {
      retryAttempts: 3,
      retryDelayMs: 0,
    });
    await vi.advanceTimersByTimeAsync(30000);
    const result = await resultPromise;

    expect(result.status).toBe(502);
    expect(await result.json()).toMatchObject({
      error_code: "BACKEND_UPSTREAM_UNAVAILABLE",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(log).toHaveBeenCalledWith(
      "[BackendProxy] canonical_upstream_unavailable",
      expect.objectContaining({
        upstream_path: "/api/auth/first-run",
        abort_origin: "proxy_deadline",
      }),
    );
  });

  it("still retries a fast connection reset on a safe GET without retrying POST", async () => {
    const failure = Object.assign(new Error("Connection reset"), {
      code: "ECONNRESET",
    });
    const fetchSpy = vi.fn()
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(new Response("Recovered", { status: 200 }));
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/auth/first-run");
    const response = await proxyToBackend(request, "/api/auth/first-run", {
      retryAttempts: 3,
      retryDelayMs: 0,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("Recovered");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls.every((call) => call[1]?.method === "GET")).toBe(true);
  });

  it("does not repeat an execution POST after an upstream 307 redirect", async () => {
    const fetchSpy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("Execution was not completed", {
        status: 307,
        headers: { location: "/api/copilot/other" },
      }),
    );
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/copilot/assist", {
      method: "POST",
      headers: { cookie: "session=caller-A", "content-type": "application/json" },
      body: JSON.stringify({ user_id: "untrusted", message: "Execute once" }),
    });
    const result = await proxyToBackend(request, "/api/copilot/assist", {
      retryAttempts: 1,
      retryOnStatusCodes: [],
      followRedirects: false,
    });

    expect(result.status).toBe(502);
    expect(await result.json()).toMatchObject({ error_code: "BACKEND_REDIRECT_REJECTED" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toBe("session=caller-A");
    // Internal Docker URL and redirect targets are never exposed to clients.
    expect(result.headers.get("location")).toBeNull();
  });

  it("preserves existing redirect behavior for ordinary non-execution requests", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response("", {
        status: 301,
        headers: { location: "/api/public/info" },
      }))
      .mockResolvedValueOnce(new Response("OK", { status: 200 }));
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/public/info");
    const response = await proxyToBackend(request, "/api/public/info", {
      retryAttempts: 1,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("OK");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});

describe("Hosted backend target single-owner contract", () => {
  it("keeps backend routing and URL validation in the server proxy, not Next build logging", () => {
    const nextConfig = readFileSync(resolve(process.cwd(), "next.config.ts"), "utf8");
    const proxy = readFileSync(
      resolve(process.cwd(), "src/app/api/_lib/backend-proxy.ts"), "utf8",
    );
    expect(nextConfig).not.toContain("process.env.KAREN_BACKEND_URL");
    expect(nextConfig).not.toContain("process.env.BACKEND_URL");
    expect(nextConfig).not.toContain("RESOLVED backendBaseUrl");
    expect(nextConfig).not.toContain("http://localhost:8000");
    expect(proxy).toContain("const EXPLICIT_BACKEND_URL = HOSTED_ON_VERCEL");
    expect(proxy).toContain("if (!EXPLICIT_BACKEND_URL.trim()) return 'missing'");
    expect(proxy).toContain("getBackendTargetStatus()");
    expect(proxy).toContain("BACKEND_TARGET_NOT_CONFIGURED");
  });
});
