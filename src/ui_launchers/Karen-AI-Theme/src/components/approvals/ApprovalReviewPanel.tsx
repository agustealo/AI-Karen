"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRuntimeApprovalContext } from "./RuntimeApprovalProvider";
import { canDecideRuntimeApproval } from "./useRuntimeApprovals";

type ApprovalReviewPanelProps = {
  id: string;
  testId: string;
  isAuthenticated: boolean;
  showRefresh?: boolean;
  onAskKaren?: () => void;
  onOpenConversation?: (conversationId: string) => Promise<void>;
};

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

/** Shared review presentation. The persistent principal-scoped provider owns
 * every read, confirmation, in-flight decision and reconciliation. */
export function ApprovalReviewPanel({ id, testId, isAuthenticated, showRefresh = false, onAskKaren, onOpenConversation }: ApprovalReviewPanelProps) {
  const {
    approvals, approvalsError, decidingApprovalId, pendingApprovalDecision,
    setPendingApprovalDecision, isLoadingApprovals, approvalDecisionError,
    approvalDecisionMessage, approvalDecisionUncertain, loadApprovals, decideApproval,
  } = useRuntimeApprovalContext();
  const now = Date.now();
  const isPending = (approval: typeof approvals[number]) => approval.status === "pending" && Date.parse(approval.expires_at) > now;
  const pendingCount = approvals.filter(isPending).length;
  const approvedCount = approvals.filter((approval) => approval.status === "approved" && Date.parse(approval.expires_at) > now).length;
  // Prioritize reviewable records; preserve the backend order within groups.
  const orderedApprovals = [...approvals].sort((a, b) => Number(isPending(b)) - Number(isPending(a)));
  return (
  <section id={id} aria-label="Needs your review" className="scroll-mt-4 space-y-3" data-testid={testId}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-lg font-semibold">Needs your review</h3>
      {showRefresh && <Button type="button" size="sm" variant="outline" disabled={!isAuthenticated || isLoadingApprovals || decidingApprovalId !== null} onClick={() => void loadApprovals()}>Refresh decisions</Button>}
    </div>
    <p className="text-sm text-muted-foreground">These requests come from Karen&apos;s authorized approval service. A decision alone does not execute an action.</p>
    {isAuthenticated && !isLoadingApprovals && !approvalsError && <p className="text-xs text-muted-foreground">{pendingCount} pending · {approvedCount} approved in the returned records. This is a bounded snapshot, not a complete approval history.</p>}
    {approvalDecisionMessage && <p role="status" className="text-sm">{approvalDecisionMessage}</p>}
    {approvalDecisionError && <p role="alert" className="text-sm text-destructive">{approvalDecisionError}</p>}
    {approvalsError && <p role="alert" className="text-sm text-destructive">{approvalsError}</p>}
    {!isAuthenticated ? <p className="text-sm text-muted-foreground">Sign in to review authorized approval requests.</p> : isLoadingApprovals ? <p role="status" className="text-sm text-muted-foreground">Loading approval requests…</p> : approvalsError ? <p className="text-sm text-muted-foreground">Approval requests are unavailable. {showRefresh ? "Refresh decisions" : "Refresh runtime"} to try again.</p> : approvals.length === 0 ? (
      <p className="rounded-lg border p-4 text-sm text-muted-foreground">You’re all caught up. No actionable approval requests are available. Karen will show requests here when human review is required.</p>
    ) : orderedApprovals.map((approval) => (
      <div key={approval.approval_id} data-testid="approval-review-record" className="min-w-0 rounded-lg border p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="min-w-0 break-words font-medium">{approval.intent}</h4>
          <div className="flex flex-wrap gap-2"><Badge variant="outline">{approval.risk_level} risk</Badge><Badge variant="secondary">{approval.status}</Badge></div>
        </div>
        <p className="text-sm text-muted-foreground">Expires {formatTimestamp(approval.expires_at)}</p>
        {approval.conversation_id && (
          <p className="text-xs text-muted-foreground">Related conversation: <span className="font-mono break-all">{approval.conversation_id}</span></p>
        )}
        <p className="text-xs text-muted-foreground">Review this decision in its original conversation before asking Karen to continue. Navigating to Chat does not automatically select a conversation or execute work.</p>
        {approval.reason_codes.length > 0 && <p className="text-sm text-muted-foreground">Reasons: {approval.reason_codes.join(", ")}</p>}
        <div className="flex flex-wrap gap-2">
          {approval.conversation_id && onOpenConversation && <Button size="sm" variant="outline" onClick={() => void onOpenConversation(approval.conversation_id!)}>Open original conversation</Button>}
          {onAskKaren && <Button size="sm" variant="outline" onClick={onAskKaren}>Open Karen chat</Button>}
          {canDecideRuntimeApproval(approval) && <>
            <Button size="sm" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
              onClick={() => setPendingApprovalDecision({ approvalId: approval.approval_id, decision: "approved" })}>Review approval</Button>
            <Button size="sm" variant="outline" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
              onClick={() => setPendingApprovalDecision({ approvalId: approval.approval_id, decision: "rejected" })}>Review rejection</Button>
          </>}
          {approval.workflow_kind === "document_author_consent" && ["pending", "approved"].includes(approval.status) && Date.parse(approval.expires_at) > Date.now() && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(approval.approval_id) && (
            <Button asChild size="sm" variant="outline"><a href={`/approvals/document-consent/${approval.approval_id}`}>Review document author consent</a></Button>
          )}
        </div>
        {approval.workflow_kind === "document_author_consent" && <p className="text-sm text-muted-foreground">Document author consent requires separate authenticated review. Generic approval actions are unavailable.</p>}
        {approval.workflow_kind === "plugin_lifecycle" && <p className="text-sm text-muted-foreground">Plugin lifecycle decisions require the governed plugin workflow. Open the original conversation if available.</p>}
        {approval.workflow_kind === "unsupported_specialized" && <p className="text-sm text-muted-foreground">No supported review workflow is available for this request.</p>}
        {approval.status === "approved" && <p className="text-sm text-muted-foreground">Decision recorded. Execution is not implied.</p>}
        {Date.parse(approval.expires_at) <= Date.now() && <p className="text-sm text-muted-foreground">Authorization expired. Refresh to verify current status.</p>}
        {canDecideRuntimeApproval(approval) && pendingApprovalDecision?.approvalId === approval.approval_id && (
          <section aria-label="Confirm approval decision" className="rounded-lg border border-primary/50 bg-muted/40 p-3 space-y-2">
            <p className="font-medium">Confirm {pendingApprovalDecision.decision === "approved" ? "approval" : "rejection"}</p>
            <p className="text-sm">Request: {approval.intent}. Risk: {approval.risk_level}. Expires: {formatTimestamp(approval.expires_at)}.</p>
            <p className="text-xs text-muted-foreground">This records your decision only. Karen must separately revalidate authorization and execution state.</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                onClick={() => void decideApproval(approval.approval_id, pendingApprovalDecision.decision)}>
                Confirm {pendingApprovalDecision.decision === "approved" ? "approval" : "rejection"}
              </Button>
              <Button type="button" variant="outline" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                onClick={() => setPendingApprovalDecision(null)}>Back</Button>
            </div>
          </section>
        )}
      </div>
    ))}
  </section>
  );
}
