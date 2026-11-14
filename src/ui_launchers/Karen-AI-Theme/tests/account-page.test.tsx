import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import AccountPage from "@/components/account/AccountPage";
import { apiClient } from "@/lib/api";

const USER_ID = "11111111-1111-1111-1111-111111111111";
const TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";

const state = vi.hoisted(() => ({
  user: {
    user_id: "11111111-1111-1111-1111-111111111111",
    tenant_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  },
  currentUser: {
    user_id: "11111111-1111-1111-1111-111111111111",
    tenant_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    email: "member@example.org",
    full_name: "Member One",
    preferences: { theme: "dark" },
    roles: ["user"],
  },
  isAuthenticated: true,
  isLoading: false,
  theme: "dark",
  toast: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
  router: vi.fn(),
  setTheme: vi.fn(),
  syncUser: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: state.router }),
}));

vi.mock("@/lib/useAuth", () => ({
  useAuth: () => ({
    user: state.user,
    isAuthenticated: state.isAuthenticated,
    isLoading: state.isLoading,
    logout: state.logout,
  }),
}));

vi.mock("@/providers/theme-provider", () => ({
  useTheme: () => ({
    theme: state.theme,
    setTheme: state.setTheme,
  }),
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: state.toast }),
}));

vi.mock("@/lib/api", () => ({
  apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
}));

vi.mock("@/lib/auth", () => ({
  authService: {
    getCurrentUser: () => state.currentUser,
    updateCurrentUser: (...args: unknown[]) => state.syncUser(...args),
  },
}));

function account(changes: Record<string, unknown> = {}) {
  return {
    user_id: USER_ID,
    tenant_id: TENANT_ID,
    email: "member@example.org",
    username: "member",
    full_name: "Member One",
    roles: ["user"],
    is_active: true,
    created_at: "2026-01-01T12:00:00Z",
    last_login: null,
    preferences: { theme: "dark", notifications: { enabled: true } },
    ...changes,
  };
}

beforeEach(() => {
  state.user.user_id = USER_ID;
  state.user.tenant_id = TENANT_ID;
  state.currentUser.user_id = USER_ID;
  state.currentUser.tenant_id = TENANT_ID;
  state.currentUser.email = "member@example.org";
  state.currentUser.full_name = "Member One";
  state.currentUser.preferences.theme = "dark";
  state.isAuthenticated = true;
  state.isLoading = false;
  state.theme = "dark";
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(account());
  state.logout.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("My Account consumer contracts", () => {
  it("shows the loading state before authenticated backend truth arrives", async () => {
    let resolveLoad: (value: unknown) => void = () => undefined;
    vi.mocked(apiClient.get).mockImplementationOnce(
      () => new Promise((resolve) => { resolveLoad = resolve; }),
    );

    render(<AccountPage />);
    expect(screen.getByRole("status").textContent).toContain("Loading your account");
    expect(screen.queryByLabelText("Display name")).toBeNull();

    resolveLoad(account());
    expect(await screen.findByLabelText("Display name")).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledWith("/api/auth/me");
  });

  it("refuses a cross-tenant account payload and disables all edits", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(account({ tenant_id: "foreign-tenant" }));
    render(<AccountPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("could not verify");
    expect(screen.queryByLabelText("Display name")).toBeNull();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("keeps account controls closed on unavailable backend and permits explicit retry", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error("Backend unavailable"))
      .mockResolvedValueOnce(account());
    render(<AccountPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Backend unavailable");
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry account verification" }));
    expect(await screen.findByLabelText("Display name")).toBeTruthy();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("shows changes only after backend PUT and durable re-read agree", async () => {
    let saved = account();
    vi.mocked(apiClient.get).mockImplementation(async () => saved);
    vi.mocked(apiClient.put).mockImplementation(async (_path, payload) => {
      saved = { ...saved, ...(payload as Record<string, string>) };
      return saved;
    });

    render(<AccountPage />);
    const name = await screen.findByLabelText("Display name");
    fireEvent.change(name, { target: { value: "Member Two" } });
    expect(screen.getByRole("status").textContent).toContain("unsaved profile changes");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Profile saved",
    })));
    expect(apiClient.put).toHaveBeenCalledWith("/api/auth/me", {
      username: "member",
      full_name: "Member Two",
      email: "member@example.org",
    });
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(state.syncUser).toHaveBeenCalledWith(expect.objectContaining({
      full_name: "Member Two",
      preferences: saved.preferences,
    }));
  });

  it("does not claim a save after an ambiguous failed mutation", async () => {
    vi.mocked(apiClient.put).mockRejectedValue(new Error("receipt lost"));
    render(<AccountPage />);
    fireEvent.change(await screen.findByLabelText("Display name"), {
      target: { value: "Member Two" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Profile save not verified",
      variant: "destructive",
    })));
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("rejects an unconfirmed preference rather than applying an optimistic theme", async () => {
    vi.mocked(apiClient.put).mockResolvedValue(account({
      preferences: { theme: "system" },
    }));
    vi.mocked(apiClient.get).mockResolvedValue(account());
    render(<AccountPage />);
    await screen.findByText("Appearance");
    fireEvent.click(screen.getByText("System"));
    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Theme change not verified",
      variant: "destructive",
    })));
    expect(state.setTheme).not.toHaveBeenCalled();
    expect(apiClient.put).toHaveBeenCalledWith("/api/auth/me", {
      preferences: { theme: "system" },
    });
  });

  it("applies a verified system theme through the canonical session owner", async () => {
    let saved = account();
    vi.mocked(apiClient.get).mockImplementation(async () => saved);
    vi.mocked(apiClient.put).mockImplementation(async (_path, payload) => {
      saved = { ...saved, preferences: {
        ...saved.preferences,
        ...(payload as { preferences: Record<string, unknown> }).preferences,
      } };
      return saved;
    });

    render(<AccountPage />);
    await screen.findByText("Appearance");
    fireEvent.click(screen.getByText("System"));
    await waitFor(() => expect(state.setTheme).toHaveBeenCalledWith("system"));
    expect(state.syncUser).toHaveBeenCalledWith({ preferences: saved.preferences });
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("keeps a valid session on incorrect current password", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Current password is incorrect"));
    render(<AccountPage />);
    fireEvent.change(await screen.findByLabelText("Current password"), {
      target: { value: "Incorrect#123" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "NewStrong#123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "NewStrong#123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Password change failed",
      variant: "destructive",
    })));
    expect(state.logout).not.toHaveBeenCalled();
    expect(state.router).not.toHaveBeenCalled();
  });

  it("clears credentials and signs out after confirmed password change", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ detail: "Password updated successfully" });
    render(<AccountPage />);
    fireEvent.change(await screen.findByLabelText("Current password"), {
      target: { value: "OldStrong#123" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "NewStrong#123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "NewStrong#123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => expect(state.router).toHaveBeenCalledWith("/login?reason=password-changed"));
    expect(state.logout).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenCalledWith("/api/auth/change-password", {
      current_password: "OldStrong#123",
      new_password: "NewStrong#123",
      confirm_password: "NewStrong#123",
    });
    expect((screen.getByLabelText("Current password") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("New password") as HTMLInputElement).value).toBe("");
  });

  it("prevents cross-principal cache writes after a delayed save", async () => {
    let respond: (result: unknown) => void = () => undefined;
    vi.mocked(apiClient.put).mockImplementation(() => new Promise((resolve) => {
      respond = resolve;
    }));
    render(<AccountPage />);
    fireEvent.change(await screen.findByLabelText("Display name"), {
      target: { value: "Member Two" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    state.syncUser.mockClear();
    state.currentUser.tenant_id = "other-tenant";
    respond(account({ full_name: "Member Two" }));
    await waitFor(() => expect(state.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Profile save not verified",
      variant: "destructive",
    })));
    expect(state.syncUser).not.toHaveBeenCalled();
  });
});
