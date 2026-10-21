import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const source = readFileSync(
  fileURLToPath(new URL("./AgentsPage.tsx", import.meta.url)),
  "utf8",
);

describe("AgentsPage canonical Medusa boundary", () => {
  it("uses the canonical Medusa catalog instead of the legacy agent registry", () => {
    expect(source).toContain('"/api/agent-runtime/catalog"');
    expect(source).not.toContain('apiClient.get<AgentRecord[]>("/api/agents")');
    expect(source).not.toContain('apiClient.post<AgentRecord>("/api/agents/"');
  });

  it("surfaces real run-level control instead of fake agent daemon controls", () => {
    expect(source).toContain('"/api/admin/agents/runs?include_terminal=true"');
    expect(source).toContain("/api/admin/agents/runs/");
    expect(source).toContain("Cancel run");
    expect(source).not.toContain("terminate");
    expect(source).not.toContain("Delete agent");
    expect(source).not.toContain("Create agent");
  });

  it("keeps execution authority in ChatRuntime and RuntimePolicy", () => {
    expect(source).toContain("Ask Karen");
    expect(source).toContain("Your AI workspace");
    expect(source).toContain('data-testid="agent-workspace"');
    expect(source).toContain("CORTEX and RuntimePolicy approval");
    expect(source).toContain("ChatRuntime after CORTEX");
    expect(source).toContain("Per-agent daemon");
  });
});

describe("Agent Runtime task-first UI contract", () => {
  it("offers master-detail, filtering and progressive diagnostics", () => {
    expect(source).toContain('aria-label="Execution list"');
    expect(source).toContain('aria-label="Selected execution details"');
    expect(source).toContain("setSelectedRunId");
    expect(source).toContain("setWorkFilter");
    expect(source).toContain("<details");
    expect(source).toContain("Technical details");
  });

  it("does not misrepresent admin history as personal work or cancellation as completion", () => {
    expect(source).toContain("/api/agent-runtime/my-runs");
    expect(source).toContain("Only your verified Medusa runs appear here.");
    expect(source).toContain("Request cancellation");
    expect(source).toContain("Cancellation requested for");
  });
});

describe("Agent Runtime governed approvals", () => {
  it("uses backend-owned approval records and decisions without auto-execution", () => {
    expect(source).toContain('"/api/approvals/"');
    expect(source).toContain("/api/approvals/\u0024{encodeURIComponent(approvalId)}/decision");
    expect(source).toContain('data-testid="agent-runtime-approvals"');
    expect(source).toContain("Approve");
    expect(source).toContain("Reject");
    expect(source).toContain("A decision alone does not execute an action.");
    expect(source).toContain("Karen must still revalidate and resume the original request.");
  });
});

describe("Agent Runtime provenance and continuation", () => {
  it("shows conversation association without pretending navigation resumes a request", () => {
    expect(source).toContain("Related conversation:");
    expect(source).toContain("Open Karen chat");
    expect(source).toContain("does not automatically select a conversation or execute work");
    expect(source).toContain("A saved artifact is not implied by this status.");
    expect(source).toContain("Cancellation requested, awaiting confirmed terminal status.");
  });
});

describe("Agent Runtime owner-verified execution detail", () => {
  it("loads selected consumer run details from backend and retains admin read boundary", () => {
    expect(source).toContain("/api/agent-runtime/my-runs/");
    expect(source).toContain("/api/admin/agents/runs/");
    expect(source).toContain("setVerifiedRun(null)");
    expect(source).toContain("Verifying execution access…");
    expect(source).toContain("if (active) setVerifiedRun(record)");
    expect(source).toContain("return () => { active = false; }");
  });
});
