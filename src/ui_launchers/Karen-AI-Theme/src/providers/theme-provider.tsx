"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/lib/useAuth";

export type Theme = "light" | "dark" | "system";

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};

function canonicalTheme(value: unknown): Theme {
  return value === "light" || value === "dark" || value === "system" ? value : "dark";
}

interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const { isAuthenticated, user } = useAuth();

  // The authenticated account record is the single source of truth. In
  // particular, never read the previous user's global localStorage theme.
  const principal = isAuthenticated && user?.user_id && user?.tenant_id
    ? JSON.stringify([user.tenant_id, user.user_id])
    : "";
  const persistedTheme = canonicalTheme(principal ? user?.preferences?.theme : undefined);

  const [preview, setPreview] = useState<{
    principal: string;
    baseline: Theme;
    value: Theme;
  } | null>(null);

  // Preview is scoped to both tenant and user and is invalidated whenever
  // the canonical server-backed preference changes.
  const theme = preview?.principal === principal && preview.baseline === persistedTheme
    ? preview.value
    : persistedTheme;

  const setTheme = useCallback((value: Theme) => {
    setPreview({ principal, baseline: persistedTheme, value: canonicalTheme(value) });
  }, [principal, persistedTheme]);

  useEffect(() => {
    const root = window.document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      root.classList.toggle("dark", dark);
      root.classList.toggle("light", !dark);
      root.style.colorScheme = dark ? "dark" : "light";
    };

    applyTheme();
    media.addEventListener?.("change", applyTheme);
    return () => {
      media.removeEventListener?.("change", applyTheme);
    };
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
