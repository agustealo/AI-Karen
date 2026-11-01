import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import {
  getBackendBaseUrl,
  proxyToBackend,
  sanitizeHeaders,
} from "@/app/api/_lib/backend-proxy";

const nativeFetch = globalThis.fetch;

function request(method: string, path = "/api/conversations") {
  return new NextRequest("http://localhost:3000" + path, {
    method,
    ...(method === "GET" || method === "HEAD"
      ? {}
      : {
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ message: "execute once" }),
        }),
  });
}

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("single canonical backend proxy authority", () => {
  it("logs only a sanitized backend scope and known error code, never the configured address", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const cause = Object.assign(
      new Error("Unable to connect to https://secrets@backend-host.example"),
      { code: "ENOTFOUND" },
    );
    const fetchSpy = vi.fn().mockRejectedValue(
      Object.assign(new TypeError("fetch failed"), { cause }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const result = await proxyToBackend(request("GET"), "/ready", {
      retryAttempts: 1,
    });
    expect(result.status).toBe(502);
    expect(spy).toHaveBeenCalledWith(
      "[BackendProxy] canonical_upstream_unavailable",
      expect.objectContaining({
        target_scope: expect.any(String),
        configuration_source: expect.any(String),
        cause_code: "ENOTFOUND",
        error_type: "TypeError",
      }),
    );
    const serialized = JSON.stringify(spy.mock.calls);
    expect(serialized).not.toContain("backend-host.example");
    expect(serialized).not.toContain("secrets");
    expect((await result.text())).not.toContain("backend-host.example");
  });

  it.each([
    ["http://127.0.0.1:8000", "loopback"],
    ["http://api:8000", "docker_only"],
    ["http://192.168.1.40:8000", "private_ip"],
    ["https://canonical-backend.example", "public_or_routed"],
    ["http://backend.internal:8000", "private_dns"],
  ])("classifies %s without disclosing the configured host", async (target, expectedScope) => {
    vi.stubEnv("KAREN_BACKEND_URL", target);
    vi.resetModules();
    const { proxyToBackend: configuredProxy } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    const logs = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("transport unavailable")));
    const response = await configuredProxy(request("GET"), "/ready", {
      retryAttempts: 1,
    });
    expect(response.status).toBe(502);
    expect(logs).toHaveBeenCalledWith(
      "[BackendProxy] canonical_upstream_unavailable",
      expect.objectContaining({
        configuration_source: "explicit",
        target_scope: expectedScope,
      }),
    );
    expect(JSON.stringify(logs.mock.calls)).not.toContain(new URL(target).hostname);
  });

  it("never replays a mutating POST when the backend returns an HTTP 502", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response('{"detail":"unavailable"}', { status: 502 }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const response = await proxyToBackend(request("POST"), "/api/conversations", {
      retryAttempts: 10,
      retryOnStatusCodes: [502],
    });
    expect(response.status).toBe(502);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][1].method).toBe("POST");
  });

  it("does not replay a POST when transport outcome is unknown", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchSpy = vi.fn().mockRejectedValue(
      new Error("Private backend endpoint https://secrets@internal-service.invalid"),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const response = await proxyToBackend(request("POST"), "/api/conversations", {
      retryAttempts: 12,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = await response.text();
    expect(body).toContain("BACKEND_UPSTREAM_UNAVAILABLE");
    expect(body).not.toContain("secrets");
    expect(body).not.toContain("internal-service");
  });

  it("never follows a mutating POST through a different backend", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 307,
        headers: { location: "http://other-backend:8000/internal" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const response = await proxyToBackend(request("POST"), "/api/conversations", {
      followRedirects: true,
      retryAttempts: 5,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBeNull();
  });

  it("rejects cross-origin GET redirects without replaying credentials or rewriting paths", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, {
      status: 302,
      headers: { location: "https://other-origin.example/admin?token=secret" },
    }));
    vi.stubGlobal("fetch", fetchSpy);

    const response = await proxyToBackend(request("GET"), "/api/conversations", {
      followRedirects: true,
      retryAttempts: 1,
    });
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      error_code: "BACKEND_REDIRECT_REJECTED",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("allows same-origin GET redirects to the configured backend", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response(null, {
        status: 307,
        headers: { location: "/ready" },
      }))
      .mockResolvedValueOnce(new Response('{"ready":true}', {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchSpy);
    const response = await proxyToBackend(request("GET"), "/api/conversations", {
      followRedirects: true,
      retryAttempts: 1,
    });
    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(new URL(fetchSpy.mock.calls[1][0]).pathname).toBe("/ready");
  });

  it("never repeats DELETE or PATCH even when callers request retries", async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new Error("connection reset"));
    vi.stubGlobal("fetch", fetchSpy);
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    for (const method of ["DELETE", "PATCH", "PUT"]) {
      const response = await proxyToBackend(request(method), "/api/conversations/test", {
        retryAttempts: 4,
      });
      expect(response.status).toBe(502);
    }
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("retains bounded safe GET retry behavior", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response("gateway", { status: 502 }))
      .mockResolvedValueOnce(new Response('{"ready":true}', {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchSpy);

    const response = await proxyToBackend(request("GET", "/api/health"), "/ready", {
      retryDelayMs: 0,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ready: true });
  });

  it("never forwards frontend deployment-protection credentials into the canonical API", () => {
    const headers = new Headers({
      Authorization: "Bearer user-session",
      Cookie: "_vercel_jwt=deployment-secret; kari_session=opaque; __vercel_protection_bypass=another-secret; theme=light",
      "X-Vercel-Protection-Bypass": "frontend-secret",
      "X-Vercel-Set-Bypass-Cookie": "true",
      "X-Vercel-Trusted-Oidc-Idp-Token": "frontend-oidc",
      "X-Vercel-Oidc-Token": "frontend-runtime-oidc",
      "X-Forwarded-Proto": "https",
    });
    const forwarded = sanitizeHeaders(headers, "https://backend.example");
    expect(forwarded.get("authorization")).toBe("Bearer user-session");
    expect(forwarded.get("cookie")).toBe("kari_session=opaque; theme=light");
    expect(forwarded.has("x-vercel-set-bypass-cookie")).toBe(false);
    expect(forwarded.has("x-vercel-protection-bypass")).toBe(false);
    expect(forwarded.has("x-vercel-trusted-oidc-idp-token")).toBe(false);
    expect(forwarded.has("x-vercel-oidc-token")).toBe(false);
    expect(forwarded.get("x-forwarded-proto")).toBe("https");
  });

  it("does not emit a cookie header when only deployment-protection tokens exist", () => {
    const forwarded = sanitizeHeaders(
      new Headers({ cookie: "_vercel_jwt=secret; __vercel_protection_bypass=token" }),
      "https://backend.example",
    );
    expect(forwarded.has("cookie")).toBe(false);
  });

  it.each([
    ["", "missing"],
    ["http://api:8000", "local_only"],
    ["http://127.0.0.1:8000", "local_only"],
    ["http://host.docker.internal:8000", "local_only"],
    ["not-a-backend-url", "invalid"],
    ["http://backend.example", "insecure"],
    ["https://user:password@backend.example", "invalid"],
    ["https://backend.example/path", "invalid"],
  ])("fails closed for Vercel backend %s (%s) without making a request", async (target, reason) => {
    vi.stubEnv("VERCEL", "1");
    vi.stubEnv("VERCEL_ENV", "preview");
    vi.stubEnv("KAREN_BACKEND_URL", target);
    vi.stubEnv("BACKEND_URL", "");
    vi.resetModules();
    const { getBackendTargetStatus, proxyToBackend: configuredProxy } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    expect(getBackendTargetStatus()).toBe(reason);
    const response = await configuredProxy(request("POST"), "/api/conversations");
    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toMatchObject({
      error_code: "BACKEND_TARGET_NOT_CONFIGURED",
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    if (target) expect(JSON.stringify(errors.mock.calls)).not.toContain(target);
  });

  it("rejects legacy BACKEND_URL as a hosted Vercel authority", async () => {
    vi.stubEnv("VERCEL", "1");
    vi.stubEnv("VERCEL_ENV", "preview");
    vi.stubEnv("KAREN_BACKEND_URL", "");
    vi.stubEnv("BACKEND_URL", "https://legacy-backend.example");
    vi.resetModules();
    const { getBackendTargetStatus, proxyToBackend: configuredProxy } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    expect(getBackendTargetStatus()).toBe("missing");
    const response = await configuredProxy(request("GET"), "/ready");
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error_code: "BACKEND_TARGET_NOT_CONFIGURED",
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("retains BACKEND_URL as a local compatibility alias", async () => {
    vi.stubEnv("VERCEL", "");
    vi.stubEnv("VERCEL_ENV", "");
    vi.stubEnv("KAREN_BACKEND_URL", "");
    vi.stubEnv("BACKEND_URL", "http://127.0.0.1:9988");
    vi.resetModules();
    const { getBackendBaseUrl: configured } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    expect(configured()).toBe("http://127.0.0.1:9988");
  });

  it("permits a configured HTTPS Vercel backend without choosing an alternate target", async () => {
    vi.stubEnv("VERCEL", "1");
    vi.stubEnv("VERCEL_ENV", "preview");
    vi.stubEnv("KAREN_BACKEND_URL", "https://canonical-backend.example");
    vi.stubEnv("BACKEND_URL", "");
    vi.resetModules();
    const { getBackendTargetStatus, proxyToBackend: configuredProxy } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    const spy = vi.fn().mockResolvedValue(new Response('{"status":"ok"}', {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", spy);
    expect(getBackendTargetStatus()).toBe("configured");
    const response = await configuredProxy(request("GET"), "/ready");
    expect(response.status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toBe("https://canonical-backend.example/ready");
  });

  it("keeps canonical Docker service routing when not hosted by Vercel", async () => {
    vi.stubEnv("VERCEL", "");
    vi.stubEnv("VERCEL_ENV", "");
    vi.stubEnv("KAREN_BACKEND_URL", "");
    vi.stubEnv("BACKEND_URL", "");
    vi.stubEnv("KAREN_DOCKER", "true");
    vi.resetModules();
    const { getBackendTargetStatus, getBackendBaseUrl: configured } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    expect(getBackendTargetStatus()).toBe("configured");
    expect(configured()).toBe("http://api:8000");
  });

  it("does not silently rewrite an explicitly configured backend in Docker", async () => {
    vi.stubEnv("KAREN_DOCKER", "true");
    vi.stubEnv("KAREN_BACKEND_URL", "http://127.0.0.1:9988");
    vi.resetModules();
    const { getBackendBaseUrl: configured } = await import(
      "@/app/api/_lib/backend-proxy"
    );
    expect(configured()).toBe("http://127.0.0.1:9988");
    expect(getBackendBaseUrl).toBeTypeOf("function");
  });
});
