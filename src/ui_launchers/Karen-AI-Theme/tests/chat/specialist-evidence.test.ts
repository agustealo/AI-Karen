import { describe, expect, it } from "vitest";
import { approvedSpecialistIdentity, emptyFreshSpecialistHistory, validApprovedSpecialist, matchesApprovedSpecialistReceipt, verifyFreshSpecialistEvidence, verifyAttestedSpecialistActivity, type ApprovedSpecialist } from "../../e2e/fixtures/specialist-evidence";

const approved: ApprovedSpecialist = { tenantId: "tenant", userId: "owner", provider: "local",
  model: "model", engine: "ollama", agent: "research", tool: "lookup", prompt: "read only" };
const time = (n: number) => new Date(1700000000000 + n).toISOString();
const runId = "request-a";
const callId = "00000000-0000-4000-8000-000000000001";
function fixture() {
  const run = { run_id: runId, request_id: runId, tenant_id: approved.tenantId,
    user_id: approved.userId, status: "completed", outcome_status: "success", policy_decision_id: "policy" };
  const lifecycle = { run_id: runId, truncated: false, response_source: "postgres_durable_run_ledger",
    transitions: [
      { transition_id: "created", from_status: null, to_status: "created", event_at: time(0), source: "runtime" },
      { transition_id: "running", from_status: "created", to_status: "running", event_at: time(0), source: "runtime" },
      { transition_id: "completed", from_status: "running", to_status: "completed", event_at: time(4), source: "runtime" },
    ] };
  const participation = { run_id: runId, evidence_status: "recorded", truncated: false,
    response_source: "postgres_outcome_records", receipts: [
      { receipt_id: "11111111-1111-5111-8111-111111111111", step_id: "step", specialist_id: approved.agent, phase: "started", observed_at: time(1) },
      { receipt_id: "22222222-2222-5222-8222-222222222222", step_id: "step", specialist_id: approved.agent, phase: "completed", observed_at: time(3) },
    ] };
  const tools = { run_id: runId, evidence_status: "recorded", window_limit_reached: false,
    response_source: "postgres_outcome_records", receipts: [{ receipt_id: "out_tool_" + callId.replace(/-/g, ""), tool_call_id: callId,
      tool_name: approved.tool, tool_version: null, agent_id: approved.agent, step_id: "step",
      policy_decision_id: "policy", success: true, error_type: null, result_sha256: "a".repeat(64), recorded_at: time(2),
      execution_scope: "tool_runtime_acknowledgment", independently_verified: false }] };
  return { run, lifecycle, participation, tools };
}
describe("ordinary specialist evidence contract", () => {
  it("accepts only a same-run, same-step tool acknowledgment", () => {
    const { run, lifecycle, participation, tools } = fixture();
    expect(verifyFreshSpecialistEvidence(runId, approved, run, lifecycle, participation, tools).toolCallId).toBe(callId);
  });
  it("does not use transition UUID ordering to infer same-timestamp lifecycle order", () => {
    const { run, lifecycle, participation, tools } = fixture();
    const reordered = { ...lifecycle, transitions: [lifecycle.transitions[1], lifecycle.transitions[0], lifecycle.transitions[2]] };
    expect(verifyFreshSpecialistEvidence(runId, approved, run, reordered, participation, tools).toolCallId).toBe(callId);
  });
  it("rejects foreign, truncated, missing, failed and contradictory evidence", () => {
    const { run, lifecycle, participation, tools } = fixture();
    for (const bad of [
      { run: { ...run, request_id: "foreign" } },
      { run: { ...run, tenant_id: "foreign" } },
      { run: { ...run, outcome_status: "partial" } },
      { lifecycle: { ...lifecycle, truncated: true } },
      { participation: { ...participation, receipts: participation.receipts.slice(0, 1) } },
      { tools: { ...tools, window_limit_reached: true } },
      { tools: { ...tools, receipts: [] } },
      { tools: { ...tools, receipts: [tools.receipts[0], tools.receipts[0]] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], receipt_id: "forged" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], tool_call_id: "fake" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], result_sha256: null }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], result_sha256: "a".repeat(64) + "\n" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], error_type: "failure" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], step_id: "foreign" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], policy_decision_id: "foreign" }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], success: false }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], independently_verified: true }] } },
      { tools: { ...tools, receipts: [{ ...tools.receipts[0], recorded_at: time(5) }] } },
    ]) {
      const changed = { run, lifecycle, participation, tools, ...bad };
      expect(() => verifyFreshSpecialistEvidence(runId, approved, changed.run, changed.lifecycle, changed.participation, changed.tools)).toThrow();
    }
  });
  it("requires approved executor identity and attested request, not generic provider text", () => {
    const receipt = { runtime_request_id: runId, actual_provider: approved.provider, actual_model: approved.model,
      runtime_engine: approved.engine, response_source: "deepagents_verified_output" };
    expect(matchesApprovedSpecialistReceipt(receipt, approved)).toBe(true);
    for (const bad of [{ runtime_request_id: "foreign\n" }, { runtime_request_id: undefined },
      { actual_model: "other" }, { response_source: "tool" }, { degraded_mode: true }, { fallback_level: 1 }]) {
      expect(matchesApprovedSpecialistReceipt({ ...receipt, ...bad }, approved)).toBe(false);
    }
  });
  it("requires an empty verified history and an explicitly configured local engine", () => {
    const empty = { threadId: "thread", messages: [], replayEvents: [], recovery_run: null };
    expect(emptyFreshSpecialistHistory(empty, "thread")).toBe(true);
    for (const bad of [{ threadId: "foreign" }, { messages: [{}] }, { replayEvents: [{}] },
      { recovery_run: {} }, { recovery_run: undefined }]) {
      expect(emptyFreshSpecialistHistory({ ...empty, ...bad }, "thread")).toBe(false);
    }
    expect(validApprovedSpecialist(approved)).toBe(true);
    for (const bad of [{ engine: "remote_api" }, { engine: "custom" }, { tenantId: "default" }, { userId: "" }]) {
      expect(validApprovedSpecialist({ ...approved, ...bad })).toBe(false);
    }
  });
  it("requires affirmative verified session and refuses administrative or foreign identities", () => {
    const session = { valid: true, session_valid: true, authenticated: true,
      user: { user_id: approved.userId, tenant_id: approved.tenantId, roles: ["member"] } };
    expect(approvedSpecialistIdentity(session, approved)).toBe(true);
    expect(approvedSpecialistIdentity({ ...session, valid: false }, approved)).toBe(false);
    expect(approvedSpecialistIdentity({ ...session, user: { ...session.user, roles: ["super_admin"] } }, approved)).toBe(false);
    expect(approvedSpecialistIdentity({ ...session, user: { ...session.user, tenant_id: "foreign" } }, approved)).toBe(false);
  });
});

describe("fresh assistant-bound specialist activity", () => {
  const thread = "thread";
  const assistant = "assistant";
  const transport = "transport-a";
  const step = (status: string, event_type: string, sequence: number) => ({
    type: "CUSTOM", name: "karen.agent_step.v1", messageId: assistant,
    value: { step_id: "step", agent_id: approved.agent, status, event_type,
      description: "Observed activity", run_id: transport, sequence },
  });
  const started = step("running", "agent_step_started", 2);
  const completed = step("completed", "agent_step_completed", 9);
  const internal = step("completed", "deepagents_plan_completed", 5);
  const receipt = { type: "CUSTOM", name: "karen.execution_receipt.v1", messageId: assistant,
    value: { runtime_request_id: runId, actual_provider: approved.provider, actual_model: approved.model,
      runtime_engine: approved.engine, response_source: "deepagents_verified_output" } };
  const history = { threadId: thread, recovery_run: null, messages: [
    { id: "user", role: "user", content: "Approved prompt" },
    { id: assistant, role: "assistant", content: "Answer" },
  ], replayEvents: [started, internal, completed, receipt] };
  const verify = (value: unknown) => verifyAttestedSpecialistActivity(value, thread, assistant, transport, runId, approved, "step");
  it("joins the exact message and transport run to ordered outer invocation evidence", () => {
    expect(verify(history)).toEqual({ startedSequence: 2, completedSequence: 9 });
  });
  it("rejects stale, cross-run, misbound, contradictory and internal-only evidence", () => {
    for (const replayEvents of [
      [receipt], [internal, receipt], [started, receipt], [completed, started, receipt],
      [started, { ...completed, messageId: "foreign" }, receipt],
      [started, { ...completed, value: { ...completed.value, run_id: "foreign" } }, receipt],
      [started, { ...completed, value: { ...completed.value, step_id: "foreign" } }, receipt],
      [started, { ...completed, value: { ...completed.value, agent_id: "foreign" } }, receipt],
      [started, step("failed", "agent_step_failed", 5), completed, receipt],
      [started, step("completed", "agent_step_completed", 2), receipt],
      [started, completed, completed, receipt],
      [started, completed, { ...receipt, value: { ...receipt.value, runtime_request_id: "foreign" } }],
      [started, completed, { ...receipt, messageId: "foreign" }],
      [started, completed, receipt, receipt],
    ]) expect(() => verify({ ...history, replayEvents })).toThrow();
    expect(() => verify({ ...history, recovery_run: {} })).toThrow();
    expect(() => verify({ ...history, messages: [...history.messages, history.messages[1]] })).toThrow();
  });
});
