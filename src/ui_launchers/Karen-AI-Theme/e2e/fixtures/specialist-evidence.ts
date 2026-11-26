export const phases = {
  started: "Method entered",
  completed: "Invocation returned",
  failed: "Invocation failed",
  interrupted: "Invocation interrupted",
  skipped: "Invocation skipped",
} as const;
type ParticipationRow = {
  receipt_id: string;
  step_id: string;
  specialist_id: string;
  phase: keyof typeof phases;
  observed_at: string;
};
export type ParticipationReadback = {
  run_id: string;
  evidence_status: "recorded" | "empty";
  receipts: ParticipationRow[];
  truncated: false;
  response_source: "postgres_outcome_records";
};

function hasExactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}

// Validate the raw wire payload before casting or comparing. Never include
// unexpected fields or their values in a diagnostic.
export function parseParticipation(value: unknown, runId: string, expectedStatus: "recorded" | "empty" = "recorded"): ParticipationReadback {
  if (!hasExactKeys(value, ["run_id", "evidence_status", "receipts", "truncated", "response_source"])
      || value.run_id !== runId || value.response_source !== "postgres_outcome_records"
      || value.evidence_status !== expectedStatus || value.truncated !== false
      || !Array.isArray(value.receipts) || value.receipts.length > 100
      || (expectedStatus === "empty" ? value.receipts.length !== 0 : value.receipts.length === 0)) {
    throw new Error("Invalid or unexpected participation envelope");
  }
  const ids = new Set<string>();
  let terminal = false;
  for (const row of value.receipts) {
    if (!hasExactKeys(row, ["receipt_id", "step_id", "specialist_id", "phase", "observed_at"])
        || typeof row.receipt_id !== "string"
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.receipt_id)
        || ids.has(row.receipt_id)
        || typeof row.specialist_id !== "string" || !row.specialist_id.trim()
        || typeof row.step_id !== "string" || !row.step_id.trim()
        || typeof row.phase !== "string" || !Object.prototype.hasOwnProperty.call(phases, row.phase)
        || typeof row.observed_at !== "string" || !Number.isFinite(Date.parse(row.observed_at))) {
      throw new Error("Invalid or unexpected participation receipt");
    }
    ids.add(row.receipt_id);
    terminal ||= row.phase !== "started";
  }
  if (expectedStatus === "recorded" && !terminal) throw new Error("Terminal observation fixture required");
  return value as ParticipationReadback;
}

export function sameParticipation(left: ParticipationReadback, right: ParticipationReadback): boolean {
  return left.run_id === right.run_id && left.evidence_status === right.evidence_status
    && left.receipts.length === right.receipts.length
    && left.receipts.every((row, index) => {
      const other = right.receipts[index];
      return row.receipt_id === other.receipt_id && row.step_id === other.step_id
        && row.specialist_id === other.specialist_id && row.phase === other.phase
        && row.observed_at === other.observed_at;
    });
}


export type ApprovedSpecialist = {
  tenantId: string;
  userId: string;
  provider: string;
  model: string;
  engine: string;
  agent: string;
  tool: string;
  prompt: string;
};

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function bounded(value: unknown, max = 256): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max &&
    value.trim() === value && !/[\x00-\x1f\x7f]/.test(value);
}

export function validRuntimeRequestId(value: unknown): value is string {
  return bounded(value, 128) && !/[^A-Za-z0-9_-]/.test(value);
}

// Keep this acceptance-only subset aligned with the backend RuntimeEngine enum.
// An engine label is attribution, not independent physical locality proof.
const localEngineIds = new Set(["lmstudio", "vllm", "sglang", "llamacpp", "tensorrt_llm", "ollama", "transformers"]);

export function validApprovedSpecialist(approved: ApprovedSpecialist): boolean {
  return [approved.tenantId, approved.userId, approved.provider, approved.model, approved.agent, approved.tool]
    .every(value => bounded(value)) &&
    !["default", "dev-tenant"].includes(approved.tenantId.toLowerCase()) &&
    localEngineIds.has(approved.engine) && !!approved.prompt.trim() && approved.prompt.length <= 2000;
}

export function emptyFreshSpecialistHistory(value: unknown, threadId: string): boolean {
  return record(value) && value.threadId === threadId &&
    value.recovery_run === null && Array.isArray(value.messages) &&
    value.messages.length === 0 && Array.isArray(value.replayEvents) && value.replayEvents.length === 0;
}

export function matchesApprovedSpecialistReceipt(value: unknown, approved: ApprovedSpecialist): boolean {
  return validApprovedSpecialist(approved) && record(value) && validRuntimeRequestId(value.runtime_request_id) &&
    value.actual_provider === approved.provider && value.actual_model === approved.model &&
    value.runtime_engine === approved.engine && value.response_source === "deepagents_verified_output" &&
    (value.degraded_mode === undefined || value.degraded_mode === false) &&
    (value.fallback_level === undefined || value.fallback_level === null || value.fallback_level === 0);
}

export function approvedSpecialistIdentity(value: unknown, approved: ApprovedSpecialist): boolean {
  if (!validApprovedSpecialist(approved) || !record(value) || value.valid !== true || value.session_valid !== true ||
      value.authenticated !== true || !record(value.user)) return false;
  const user = value.user;
  return user.user_id === approved.userId && user.tenant_id === approved.tenantId &&
    Array.isArray(user.roles) && user.roles.length > 0 &&
    user.roles.every(role => typeof role === "string" &&
      !/(?:admin|administrator)/i.test(role));
}

/**
 * Check exact durable identities and the acknowledged tool/step relationship,
 * not text that claims an action ran. This is intentionally a one-tool,
 * successful single-specialist trial; a saturated or degraded run fails.
 */
export function verifyFreshSpecialistEvidence(
  runId: string, approved: ApprovedSpecialist, run: unknown, lifecycle: unknown,
  participation: unknown, tools: unknown,
): { stepId: string; toolCallId: string; toolReceiptId: string; participationIds: string[]; transitionIds: string[] } {
  if (!validApprovedSpecialist(approved) || !validRuntimeRequestId(runId) || !record(run) ||
      run.run_id !== runId || run.request_id !== runId ||
      run.tenant_id !== approved.tenantId || run.user_id !== approved.userId ||
      run.status !== "completed" || run.outcome_status !== "success" ||
      !bounded(run.policy_decision_id)) {
    throw new Error("Fresh specialist run identity or successful outcome unavailable");
  }
  if (!hasExactKeys(lifecycle, ["run_id", "transitions", "truncated", "response_source"]) ||
      lifecycle.run_id !== runId || lifecycle.truncated !== false ||
      lifecycle.response_source !== "postgres_durable_run_ledger" ||
      !Array.isArray(lifecycle.transitions) || lifecycle.transitions.length !== 3) {
    throw new Error("Exact durable specialist lifecycle unavailable");
  }
  // Creation and running may have the exact same timestamp. Validate the
  // semantic chain and unique transition identities rather than UUID sort order.
  const expectedTransitions = [[null, "created"], ["created", "running"], ["running", "completed"]] as const;
  const transitionIds: string[] = [];
  const times: number[] = [];
  for (const [from, to] of expectedTransitions) {
    const matching = lifecycle.transitions.filter(item => record(item) && item.to_status === to);
    const item: unknown = matching.length === 1 ? matching[0] : undefined;
    if (!hasExactKeys(item, ["transition_id", "from_status", "to_status", "event_at", "source"]) ||
        !bounded(item.transition_id) || transitionIds.includes(item.transition_id) ||
        item.from_status !== from || item.source !== "runtime" || typeof item.event_at !== "string") {
      throw new Error("Invalid durable specialist transition");
    }
    const time = Date.parse(item.event_at);
    if (!Number.isFinite(time) || (times.length > 0 && time < times[times.length - 1])) {
      throw new Error("Invalid durable lifecycle time");
    }
    times.push(time);
    transitionIds.push(item.transition_id);
  }
  const startedAt = times[1];
  const completedAt = times[2];
  const observations = parseParticipation(participation, runId);
  const entered = observations.receipts.filter(row => row.phase === "started");
  const returned = observations.receipts.filter(row => row.phase === "completed");
  if (observations.receipts.length !== 2 || entered.length !== 1 || returned.length !== 1 ||
      entered[0].specialist_id !== approved.agent || returned[0].specialist_id !== approved.agent ||
      entered[0].step_id !== returned[0].step_id ||
      Date.parse(entered[0].observed_at) < startedAt ||
      Date.parse(returned[0].observed_at) > completedAt ||
      Date.parse(entered[0].observed_at) > Date.parse(returned[0].observed_at)) {
    throw new Error("Exact completed specialist invocation unavailable");
  }
  if (!hasExactKeys(tools, ["run_id", "evidence_status", "receipts", "window_limit_reached", "response_source"]) ||
      tools.run_id !== runId || tools.evidence_status !== "recorded" ||
      tools.window_limit_reached !== false || tools.response_source !== "postgres_outcome_records" ||
      !Array.isArray(tools.receipts) || tools.receipts.length !== 1) {
    throw new Error("Exactly one bounded governed tool acknowledgment required");
  }
  const row = tools.receipts[0];
  if (!hasExactKeys(row, ["receipt_id", "tool_call_id", "tool_name", "tool_version", "agent_id",
      "step_id", "policy_decision_id", "success", "error_type", "result_sha256", "recorded_at",
      "execution_scope", "independently_verified"]) ||
      typeof row.tool_call_id !== "string" || row.tool_call_id.length !== 36 ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.tool_call_id) ||
      row.receipt_id !== "out_tool_" + row.tool_call_id.replace(/-/g, "") ||
      row.tool_name !== approved.tool || row.agent_id !== approved.agent ||
      row.step_id !== entered[0].step_id || row.policy_decision_id !== run.policy_decision_id ||
      row.success !== true || row.error_type !== null ||
      row.execution_scope !== "tool_runtime_acknowledgment" || row.independently_verified !== false ||
      !(row.tool_version === null || bounded(row.tool_version)) ||
      typeof row.result_sha256 !== "string" || row.result_sha256.length !== 64 || /[^0-9a-f]/.test(row.result_sha256) ||
      typeof row.recorded_at !== "string" || !Number.isFinite(Date.parse(row.recorded_at)) ||
      Date.parse(row.recorded_at) < Date.parse(entered[0].observed_at) ||
      Date.parse(row.recorded_at) > Date.parse(returned[0].observed_at)) {
    throw new Error("Invalid or unlinked governed tool acknowledgment");
  }
  return {
    stepId: entered[0].step_id, toolCallId: row.tool_call_id, toolReceiptId: row.receipt_id,
    participationIds: [entered[0].receipt_id, returned[0].receipt_id], transitionIds,
  };
}
