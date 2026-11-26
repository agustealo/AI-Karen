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

  it("preserves binary audio/wav response and request bytes without UTF-8 corruption", async () => {
    // Bytes containing invalid UTF-8 sequences (0xff, 0xfe, 0x80) that .text() would mangle into U+FFFD
    const wavBytes = new Uint8Array([
      0x52, 0x49, 0x46, 0x46, 0x24, 0x80, 0x00, 0x00,
      0x57, 0x41, 0x56, 0x45, 0xff, 0xfe, 0x81, 0x90,
    ]);
    let forwardedBody: unknown;
    const fetchSpy = vi.fn().mockImplementation(async (_url, init?: RequestInit) => {
      forwardedBody = init?.body;
      return new Response(wavBytes, {
        status: 200,
        headers: { "content-type": "audio/wav" },
      });
    });
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/voice/engines/pocket-tts/synthesis", {
      method: "POST",
      headers: { "content-type": "audio/wav" },
      body: wavBytes,
    });
    const response = await proxyToBackend(request, "/api/voice/engines/pocket-tts/synthesis", {
      retryAttempts: 1,
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("audio/wav");
    const received = new Uint8Array(await response.arrayBuffer());
    expect(Array.from(received)).toEqual(Array.from(wavBytes));
    expect(forwardedBody).toBeInstanceOf(ArrayBuffer);
    expect(Array.from(new Uint8Array(forwardedBody as ArrayBuffer))).toEqual(Array.from(wavBytes));
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


describe("Bounded Communications wait proxy policy", () => {
  const path = "/api/communications-center/inbox/wait";

  it.each([502, 307])("never replays wait status %s even with read retry options", async (status) => {
    const fetchSpy = vi.fn().mockImplementation(() => Promise.resolve(new Response(null, {
      status, headers: { location: "/api/communications-center/inbox/wait" },
    })));
    globalThis.fetch = fetchSpy as typeof fetch;
    const response = await proxyToBackend(new NextRequest("http://localhost:3000" + path), path, {
      retryAttempts: 5, followRedirects: true, retryOnStatusCodes: [502],
    });
    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("location")).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("does not send an already-cancelled wait", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    controller.abort("private cancellation reason");
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy as typeof fetch;
    const logs = vi.spyOn(console, "error").mockImplementation(() => {});
    const response = await proxyToBackend(
      new NextRequest("http://localhost:3000" + path, { signal: controller.signal }), path,
    );
    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(logs).toHaveBeenCalledWith("[BackendProxy] canonical_upstream_unavailable",
      expect.objectContaining({ abort_origin: "client_disconnect" }));
    expect(JSON.stringify(logs.mock.calls)).not.toContain("private cancellation reason");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("propagates browser disconnect and releases the upstream deadline", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    let entered!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const logs = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchSpy = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        entered();
      }),
    );
    globalThis.fetch = fetchSpy as typeof fetch;
    const request = new NextRequest("http://localhost:3000" + path, { signal: controller.signal });
    const pending = proxyToBackend(request, path, { retryAttempts: 5 });
    await started;
    controller.abort();
    const response = await pending;
    expect(response.status).toBe(502);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(logs).toHaveBeenCalledWith("[BackendProxy] canonical_upstream_unavailable",
      expect.objectContaining({ abort_origin: "client_disconnect" }));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears disconnect handling and deadline on a completed wait", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const request = new NextRequest("http://localhost:3000" + path, { signal: controller.signal });
    const remove = vi.spyOn(request.signal, "removeEventListener");
    const fetchSpy = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(new Response('{"changed":true}', { status: 200 })),
    );
    globalThis.fetch = fetchSpy as typeof fetch;
    const response = await proxyToBackend(request, path);
    expect(await response.json()).toEqual({ changed: true });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
    controller.abort();
    expect(fetchSpy.mock.calls[0][1]?.signal?.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });
});
