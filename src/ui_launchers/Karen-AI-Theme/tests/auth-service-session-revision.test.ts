import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { authService } from "@/lib/auth";

function pendingResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}

function loginResponse(token: string, email: string): Response {
  return new Response(JSON.stringify({
    access_token: token,
    refresh_token: `refresh-${token}`,
    expires_in: 3600,
    token_type: "bearer",
    user: {
      user_id: email,
      tenant_id: "test-tenant",
      email,
      full_name: email,
      roles: ["user"],
      is_active: true,
      preferences: {},
      permissions: ["chat.use"],
    },
    permissions: ["chat.use"],
  }), { status: 200, headers: { "Content-Type": "application/json" } });
}

function setPriorCredentials(): void {
  localStorage.setItem("access_token", "previous-token");
  localStorage.setItem("refresh_token", "previous-refresh");
  localStorage.setItem("user_data", JSON.stringify({
    user_id: "old-user", tenant_id: "test-tenant", email: "old@example.test",
  }));
}

beforeEach(() => {
  authService.clearAuth();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
  authService.clearAuth();
});

describe("canonical auth service session generation", () => {
  it("does not erase newer login after delayed old-session validation denial", async () => {
    setPriorCredentials();
    const validation = pendingResponse();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/validate-session")) return validation.promise;
      if (url.endsWith("/api/auth/login")) return loginResponse("new-token", "new@example.test");
      throw new Error("Unexpected auth request: " + url);
    }));
    const staleValidation = authService.validateSession();
    await Promise.resolve();
    await authService.login({ email: "new@example.test", password: "only-in-test" });
    validation.resolve(new Response("", { status: 401 }));
    await expect(staleValidation).resolves.toBe(false);
    expect(localStorage.getItem("access_token")).toBe("new-token");
    expect(authService.getCurrentUser()?.user_id).toBe("new@example.test");
  });

  it("does not write a late old-refresh token over a new login", async () => {
    setPriorCredentials();
    const refresh = pendingResponse();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/refresh")) return refresh.promise;
      if (url.endsWith("/api/auth/login")) return loginResponse("new-token", "new@example.test");
      throw new Error("Unexpected auth request: " + url);
    }));
    const staleRefresh = authService.refreshToken();
    await Promise.resolve();
    await authService.login({ email: "new@example.test", password: "only-in-test" });
    refresh.resolve(new Response(JSON.stringify({ access_token: "old-refreshed-token" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    await expect(staleRefresh).resolves.toBe("");
    expect(localStorage.getItem("access_token")).toBe("new-token");
  });

  it("does not clear a new login when an earlier logout finally completes", async () => {
    setPriorCredentials();
    const logout = pendingResponse();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/logout")) return logout.promise;
      if (url.endsWith("/api/auth/login")) return loginResponse("new-token", "new@example.test");
      throw new Error("Unexpected auth request: " + url);
    }));
    const staleLogout = authService.logout();
    await Promise.resolve();
    await authService.login({ email: "new@example.test", password: "only-in-test" });
    logout.resolve(new Response(null, { status: 204 }));
    await staleLogout;
    expect(localStorage.getItem("access_token")).toBe("new-token");
    expect(authService.getCurrentUser()?.user_id).toBe("new@example.test");
  });
});
