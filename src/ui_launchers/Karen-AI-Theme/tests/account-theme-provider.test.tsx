import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ThemeProvider, useTheme } from "@/providers/theme-provider";

const current = vi.hoisted(() => ({
  user: {
    user_id: "user-a",
    tenant_id: "tenant-a",
    preferences: { theme: "dark" },
  },
  isAuthenticated: true,
}));

vi.mock("@/lib/useAuth", () => ({
  useAuth: () => current,
}));

function Display() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setTheme("light")}>Preview light</button>
    </div>
  );
}

beforeEach(() => {
  current.isAuthenticated = true;
  current.user.user_id = "user-a";
  current.user.tenant_id = "tenant-a";
  current.user.preferences.theme = "dark";
  window.localStorage.clear();
  document.documentElement.classList.remove("dark", "light");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("authenticated display preferences", () => {
  it("uses the authenticated backend theme instead of a shared localStorage override", () => {
    window.localStorage.setItem("theme", "light");
    render(<ThemeProvider><Display /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does not preserve a former tenant's preview when accounts switch", () => {
    const view = render(<ThemeProvider><Display /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Preview light" }));
    expect(screen.getByTestId("theme").textContent).toBe("light");

    current.user.tenant_id = "tenant-b";
    view.rerender(<ThemeProvider><Display /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("dark");
  });

  it("invalidates local previews when the canonical preference changes", () => {
    const view = render(<ThemeProvider><Display /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Preview light" }));
    expect(screen.getByTestId("theme").textContent).toBe("light");

    current.user.preferences.theme = "system";
    view.rerender(<ThemeProvider><Display /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("system");
  });

  it("defaults to the safe appearance rather than leaking another user's theme on sign-out", () => {
    const view = render(<ThemeProvider><Display /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Preview light" }));
    current.isAuthenticated = false;
    view.rerender(<ThemeProvider><Display /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("dark");
  });

  it("follows the OS color scheme in system mode", () => {
    let systemDark = true;
    let fireChange: (() => void) | null = null;
    vi.spyOn(window, "matchMedia").mockImplementation(() => ({
      matches: systemDark,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_event: string, listener: EventListenerOrEventListenerObject) => {
        fireChange = () => {
          if (typeof listener === "function") listener(new Event("change"));
          else listener.handleEvent(new Event("change"));
        };
      },
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList);
    current.user.preferences.theme = "system";
    render(<ThemeProvider><Display /></ThemeProvider>);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    systemDark = false;
    fireChange?.();
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });
});
