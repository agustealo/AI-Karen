"use client";

import type { GovernedToolReceipt } from "@/lib/governed-tool-receipts";

export function GovernedToolReceiptList({ receipts }: { receipts: readonly GovernedToolReceipt[] }) {
  return (
    <ol className="space-y-2">
      {receipts.map(receipt => (
        <li key={receipt.receipt_id} className="border-t pt-2 space-y-1 break-words">
          <p className="font-medium text-foreground">
            {receipt.tool_name || "Unnamed tool"}: {receipt.success ? "Runtime acknowledged success" : "Runtime reported failure"}
          </p>
          <p>Tool version: {receipt.tool_version || "Not reported"} · Agent: {receipt.agent_id || "Unknown"}</p>
          <p className="break-all">Step: {receipt.step_id || "Unknown"} · Receipt: {receipt.receipt_id}</p>
          <p className="break-all">Policy decision: {receipt.policy_decision_id || "Unknown"}</p>
          {receipt.result_sha256 && <p className="break-all">Result digest: {receipt.result_sha256}</p>}
          {receipt.recorded_at && <p><time dateTime={receipt.recorded_at}>{new Date(receipt.recorded_at).toLocaleString()}</time></p>}
          {receipt.error_type && <p className="text-destructive">Error: {receipt.error_type}</p>}
        </li>
      ))}
    </ol>
  );
}
