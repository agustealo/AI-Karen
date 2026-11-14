import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const forwarded = vi.hoisted(() => ({ proxy: vi.fn() }));

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  proxyToBackend: forwarded.proxy,
}));

import { GET, POST, PUT } from "@/app/api/auth/[[...path]]/route";

afterEach(() => {
  vi.resetAllMocks();
});

describe("My Account same-origin authentication proxy", () => {
  it("forwards canonical GET /api/auth/me through the backend", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/me");
    forwarded.proxy.mockResolvedValue(new Response('{"user_id":"owned"}', { status: 200 }));
    const result = await GET(request);
    expect(result.status).toBe(200);
    expect(forwarded.proxy).toHaveBeenCalledWith(
      request,
      "/api/auth/me",
      expect.objectContaining({ retryAttempts: 3 }),
    );
  });

  it("forwards profile and preference PUT without mutating-request replay", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/me", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ preferences: { theme: "system" } }),
    });
    forwarded.proxy.mockResolvedValue(new Response('{"preferences":{"theme":"system"}}', { status: 200 }));

    const result = await PUT(request);
    expect(result.status).toBe(200);
    expect(forwarded.proxy).toHaveBeenCalledWith(
      request,
      "/api/auth/me",
      { retryAttempts: 1 },
    );
  });

  it("forwards password changes without retrying a security mutation", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: "wrong" }),
    });
    forwarded.proxy.mockResolvedValue(new Response('{"detail":"incorrect"}', { status: 400 }));
    const result = await POST(request);
    expect(result.status).toBe(400);
    expect(forwarded.proxy).toHaveBeenCalledWith(
      request,
      "/api/auth/change-password",
      { retryAttempts: 1 },
    );
  });

  it("keeps backend 401 and 403 decisions intact", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/me", { method: "PUT" });
    forwarded.proxy.mockResolvedValue(new Response('{"detail":"Unauthorized"}', { status: 401 }));
    expect((await PUT(request)).status).toBe(401);
    forwarded.proxy.mockResolvedValue(new Response('{"detail":"Forbidden"}', { status: 403 }));
    expect((await PUT(request)).status).toBe(403);
  });
});
