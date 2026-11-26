"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import useAuth from "@/lib/useAuth";
import { useRuntimeApprovals } from "./useRuntimeApprovals";

type ApprovalController = ReturnType<typeof useRuntimeApprovals>;
const RuntimeApprovalContext = createContext<ApprovalController | null>(null);

/**
 * One controller per authenticated principal, above workspace switching.
 * Auth revalidation, logout, and tenant/user changes discard the old controller.
 */
export function RuntimeApprovalProvider({ children }: { children: ReactNode }) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const enabled = Boolean(isAuthenticated && !isLoading && user?.tenant_id?.trim() && user?.user_id?.trim());
  const principal = enabled ? JSON.stringify([user?.tenant_id, user?.user_id]) : null;
  return <ScopedRuntimeApprovalProvider key={principal ?? "unverified"} enabled={enabled}>{children}</ScopedRuntimeApprovalProvider>;
}

function ScopedRuntimeApprovalProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const controller = useRuntimeApprovals(enabled);
  const { loadApprovals } = controller;
  useEffect(() => { void loadApprovals(); }, [loadApprovals]);
  return <RuntimeApprovalContext.Provider value={controller}>{children}</RuntimeApprovalContext.Provider>;
}

export function useRuntimeApprovalContext(): ApprovalController {
  const controller = useContext(RuntimeApprovalContext);
  if (!controller) throw new Error("RuntimeApprovalProvider is required for approval review.");
  return controller;
}
