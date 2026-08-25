"use client";

export type SetupState = "checking" | "required" | "configured" | "blocked";

export interface FirstRunStatus {
  first_run_required: boolean;
  message: string;
}

export interface SystemReadiness {
  api: "ready" | "error";
  auth: "ready" | "error";
  database: "ready" | "degraded" | "unknown";
  message?: string;
}

export interface FirstAdminInput {
  email: string;
  full_name: string;
  password: string;
  confirm_password: string;
}

export interface FirstAdminResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: Record<string, unknown>;
  permissions: string[];
  message: string;
}

class SetupService {
  private readonly timeoutMs = 10000;

  private async request(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      return await fetch(input, {
        ...init,
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async getFirstRunStatus(): Promise<FirstRunStatus> {
    const response = await this.request("/api/auth/first-run");
    if (!response.ok) {
      throw new Error(`Setup status unavailable (${response.status})`);
    }
    return response.json();
  }

  async getSystemReadiness(): Promise<SystemReadiness> {
    try {
      const [healthResponse, authResponse] = await Promise.all([
        this.request("/health"),
        this.request("/api/auth/health"),
      ]);

      if (!healthResponse.ok || !authResponse.ok) {
        return {
          api: healthResponse.ok ? "ready" : "error",
          auth: authResponse.ok ? "ready" : "error",
          database: "unknown",
          message: "One or more required services are unavailable.",
        };
      }

      const health = await healthResponse.json();
      const databaseStatus =
        health?.connections?.database?.status ?? health?.connections?.database ?? "unknown";

      return {
        api: "ready",
        auth: "ready",
        database:
          databaseStatus === "healthy"
            ? "ready"
            : databaseStatus === "degraded"
              ? "degraded"
              : "unknown",
      };
    } catch (error) {
      return {
        api: "error",
        auth: "error",
        database: "unknown",
        message: error instanceof Error ? error.message : "System readiness check failed.",
      };
    }
  }

  async createFirstAdmin(input: FirstAdminInput): Promise<FirstAdminResponse> {
    const response = await this.request("/api/auth/first-run/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });

    if (!response.ok) {
      let message = "Unable to create the first administrator.";
      try {
        const payload = await response.json();
        if (typeof payload?.detail === "string" && payload.detail.trim()) {
          message = payload.detail;
        }
      } catch {
        // Preserve the safe generic message for non-JSON failures.
      }
      throw new Error(message);
    }

    const payload: FirstAdminResponse = await response.json();
    this.adoptAuthenticatedSetup(payload);
    return payload;
  }

  private adoptAuthenticatedSetup(payload: FirstAdminResponse): void {
    try {
      localStorage.setItem("access_token", payload.access_token);
      localStorage.setItem("refresh_token", payload.refresh_token);
      localStorage.setItem("user_data", JSON.stringify(payload.user));
      localStorage.setItem("kari_session_expected", "true");
      localStorage.setItem("kari_login_success_at", String(Date.now()));
    } catch {
      // The backend-owned HttpOnly cookie remains the session authority.
    }
  }
}

export const setupService = new SetupService();
