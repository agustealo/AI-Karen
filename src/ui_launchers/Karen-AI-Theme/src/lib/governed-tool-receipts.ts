/** Canonical read-only wire contract for saved-task and personal Medusa tool acknowledgments. */
export type GovernedToolReceipt = {
  receipt_id: string;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_version: string | null;
  policy_decision_id: string | null;
  agent_id: string | null;
  step_id: string | null;
  success: boolean;
  error_type: string | null;
  result_sha256: string | null;
  recorded_at: string | null;
  execution_scope: "tool_runtime_acknowledgment";
  independently_verified: false;
};

/** Correlated run evidence is stricter than the legacy saved-task projection. */
export type RunGovernedToolReceipt = GovernedToolReceipt & {
  tool_call_id: string;
  tool_name: string;
  policy_decision_id: string;
  agent_id: string;
  step_id: string;
  recorded_at: string;
};

export interface RunToolReceiptsResponse {
  run_id: string;
  evidence_status: "recorded" | "empty";
  receipts: RunGovernedToolReceipt[];
  window_limit_reached: boolean;
  response_source: "postgres_outcome_records";
}

function exactRecord(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}

function boundedText(value: unknown, max = 256): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max
    && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
}

/** Strict owner-run projection. Legacy saved-task fields may be nullable;
 * the correlated run API requires concrete tool, agent, step and policy IDs. */
export function isRunToolReceiptsResponse(value: unknown): value is RunToolReceiptsResponse {
  if (!exactRecord(value, ["run_id", "evidence_status", "receipts", "window_limit_reached", "response_source"])
    || !boundedText(value.run_id, 128) || value.response_source !== "postgres_outcome_records"
    || !Array.isArray(value.receipts) || value.receipts.length > 100
    || value.evidence_status !== (value.receipts.length ? "recorded" : "empty")
    || value.window_limit_reached !== (value.receipts.length === 100)) return false;
  const calls = new Set<string>();
  for (const row of value.receipts) {
    if (!exactRecord(row, ["receipt_id", "tool_call_id", "tool_name", "tool_version",
      "policy_decision_id", "agent_id", "step_id", "success", "error_type", "result_sha256",
      "recorded_at", "execution_scope", "independently_verified"])
      || typeof row.tool_call_id !== "string"
      || row.tool_call_id.length !== 36
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.tool_call_id)
      || row.receipt_id !== "out_tool_" + row.tool_call_id.replace(/-/g, "")
      || calls.has(row.tool_call_id)
      || ![row.tool_name, row.agent_id, row.step_id, row.policy_decision_id].every(field => boundedText(field))
      || (row.tool_version !== null && !boundedText(row.tool_version))
      || typeof row.success !== "boolean"
      || (row.error_type !== null && !boundedText(row.error_type))
      || (row.success && row.error_type !== null)
      || (row.result_sha256 !== null && (typeof row.result_sha256 !== "string"
        || row.result_sha256.length !== 64 || /[^0-9a-f]/.test(row.result_sha256)))
      || typeof row.recorded_at !== "string" || row.recorded_at.length > 64
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(row.recorded_at)
      || /\s$/.test(row.recorded_at) || !Number.isFinite(Date.parse(row.recorded_at))
      || row.execution_scope !== "tool_runtime_acknowledgment" || row.independently_verified !== false) return false;
    calls.add(row.tool_call_id);
  }
  return true;
}
