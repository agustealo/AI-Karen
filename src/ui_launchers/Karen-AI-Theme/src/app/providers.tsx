"use client";

import type { ReactNode } from "react";

import { AuthProvider } from "@/contexts/AuthContext";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ExtensionProvider } from "@/contexts/ExtensionContext";
import { SessionBoundary } from "@/components/auth/SessionBoundary";
import { ToastProvider } from "@/contexts/ToastContext";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <AuthProvider>
          <ExtensionProvider>
            <SessionBoundary>{children}</SessionBoundary>
          </ExtensionProvider>
        </AuthProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
