"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";

export interface RuntimeApproval {
  approval_id: string;
  conversation_id?: string | null;
  intent: string;
  risk_level: string;
  reason_codes: string[];
  status: string;
  expires_at: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function isRuntimeApproval(value: unknown): value is RuntimeApproval {
  return isObject(value) && nonemptyString(value.approval_id) && nonemptyString(value.intent)
    && nonemptyString(value.risk_level) && nonemptyString(value.status)
    && (value.conversation_id == null || typeof value.conversation_id === "string")
    && Array.isArray(value.reason_codes) && value.reason_codes.every((reason) => typeof reason === "string")
    && nonemptyString(value.expires_at) && Number.isFinite(Date.parse(value.expires_at));
}

/**
 * Shared consumer controller for canonical Runtime-owned approvals.
 * Mount beneath a principal-keyed boundary; unmount on auth revalidation,
 * account or tenant changes. Consumers explicitly request initial/refresh
 * reads; visibility discovery and uncertain mutation reconciliation stay here.
 * No approval decision executes the underlying request.
 */
export function useRuntimeApprovals(isAuthenticated: boolean, onDecisionMessage: (message: string) => void) {
  const [approvals, setApprovals] = useState<RuntimeApproval[]>([]);
  const [approvalsError, setApprovalsError] = useState("");
  const [decidingApprovalId, setDecidingApprovalId] = useState<string | null>(null);
  const [pendingApprovalDecision, setPendingApprovalDecision] = useState<{ approvalId: string; decision: "approved" | "rejected" } | null>(null);
  const [isLoadingApprovals, setIsLoadingApprovals] = useState(true);
  const [approvalDecisionError, setApprovalDecisionError] = useState("");
  const [approvalDecisionUncertain, setApprovalDecisionUncertain] = useState(false);
  const approvalDecisionInFlightRef = useRef(false);
  const approvalReadRevision = useRef(0);
  const approvalLive = useRef(false);
  useLayoutEffect(() => {
    approvalLive.current = true;
    return () => {
      approvalLive.current = false;
      approvalReadRevision.current += 1;
    };
  }, []);

  const loadApprovals = useCallback(async (afterDecision = false) => {
    if (!approvalLive.current || (approvalDecisionInFlightRef.current && !afterDecision)) return;
    const revision = ++approvalReadRevision.current;
    if (!isAuthenticated) {
      setApprovals([]);
      setApprovalsError("");
      setApprovalDecisionUncertain(false);
      setIsLoadingApprovals(false);
      return;
    }
    setIsLoadingApprovals(true);
    try {
      const records = await apiClient.get<unknown>("/api/approvals/");
      if (!approvalLive.current || revision !== approvalReadRevision.current) return;
      if (!Array.isArray(records) || !records.every(isRuntimeApproval) || new Set(records.map((record) => record.approval_id)).size !== records.length) throw new Error("Approval response does not match the runtime contract.");
      setApprovals(records);
      // A confirmation belongs to the exact previously reviewed snapshot.
      setPendingApprovalDecision(null);
      setApprovalsError("");
      setApprovalDecisionUncertain(false);
      setApprovalDecisionError("");
    } catch {
      if (!approvalLive.current || revision !== approvalReadRevision.current) return;
      setApprovals([]);
      setApprovalsError("Could not load approval requests.");
    } finally {
      if (approvalLive.current && revision === approvalReadRevision.current) setIsLoadingApprovals(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const discover = () => {
      if (document.visibilityState === "visible" && !approvalDecisionInFlightRef.current) void loadApprovals();
    };
    const timer = window.setInterval(discover, 60000);
    document.addEventListener("visibilitychange", discover);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", discover); };
  }, [isAuthenticated, loadApprovals]);

  const decideApproval = useCallback(async (approvalId: string, decision: "approved" | "rejected") => {
    if (!approvalLive.current || !isAuthenticated || approvalDecisionInFlightRef.current || decidingApprovalId !== null || isLoadingApprovals || approvalsError || approvalDecisionUncertain) return;
    const approval = approvals.find((item) => item.approval_id === approvalId);
    if (!approval || approval.status !== "pending" || Date.parse(approval.expires_at) <= Date.now()) {
      setApprovalDecisionError("This approval is unavailable or expired. Refresh the list before deciding.");
      setPendingApprovalDecision(null);
      return;
    }
    approvalDecisionInFlightRef.current = true;
    approvalReadRevision.current += 1;
    setDecidingApprovalId(approvalId);
    setPendingApprovalDecision(null);
    setApprovalDecisionError("");
    try {
      const result = await apiClient.post<unknown>(
        `/api/approvals/${encodeURIComponent(approvalId)}/decision`,
        { decision },
      );
      if (!approvalLive.current) return;
      if (!isRuntimeApproval(result) || result.approval_id !== approvalId) throw new Error("Approval response could not be verified. Refresh before deciding again.");
      onDecisionMessage(
        result.status === decision
          ? `Decision recorded: ${decision}. Karen must still revalidate and resume the original request.`
          : `Approval status: ${result.status}. No action has been executed by this decision.`,
      );
      await loadApprovals(true);
    } catch {
      if (!approvalLive.current) return;
      setApprovalDecisionUncertain(true);
      setApprovalDecisionError("Decision outcome could not be verified. Refresh before attempting another decision.");
    } finally {
      approvalDecisionInFlightRef.current = false;
      setDecidingApprovalId(null);
    }
  }, [loadApprovals, approvals, decidingApprovalId, isLoadingApprovals, approvalsError, approvalDecisionUncertain, isAuthenticated, onDecisionMessage]);

  return {
    approvals, approvalsError, decidingApprovalId, pendingApprovalDecision,
    setPendingApprovalDecision, isLoadingApprovals, approvalDecisionError,
    approvalDecisionUncertain, loadApprovals, decideApproval,
  };
}
