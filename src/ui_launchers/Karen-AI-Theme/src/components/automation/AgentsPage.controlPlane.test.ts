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
    expect(source).toContain("Request cancellation");
    expect(source).not.toContain(">Cancel run<");
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
    expect(source).toContain("Cancellation endpoint responded for");
    expect(source).toContain("Cancellation outcome could not be verified.");
  });
});

describe("Agent Runtime governed approvals", () => {
  it("uses backend-owned approval records and decisions without auto-execution", () => {
    expect(source).toContain('"/api/approvals/"');
    expect(source).toContain("/api/approvals/\u0024{encodeURIComponent(approvalId)}/decision");
    expect(source).toContain('data-testid="agent-runtime-approvals"');
    expect(source).toContain("Review approval");
    expect(source).toContain("Review rejection");
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

describe("Agent Runtime discovery contract", () => {
  it("validates the canonical minimal backend catalog before rendering", () => {
    expect(source).toContain('import { isAgentCatalogResponse, type AgentCatalogResponse } from "./agentCatalog"');
    expect(source).toContain("if (!isAgentCatalogResponse(response))");
    expect(source).toContain("Registered specialists are unavailable until the catalog contract is verified.");
    expect(source).toContain("Agent catalog response does not match the discovery contract.");
    expect(source).toContain("Determined per request");
  });

  it("does not dereference metadata the discovery endpoint deliberately omits", () => {
    expect(source).not.toContain("agent.capabilities.map(");
    expect(source).not.toContain("agent.missing_dependencies.length");
    expect(source).not.toContain("{agent.description}");
    expect(source).not.toContain("{agent.version}");
    expect(source).toContain("not exposed by this discovery endpoint");
  });
});


describe("Agent Runtime truthful availability states", () => {
  it("distinguishes initial loading and retrieval errors from empty execution history", () => {
    expect(source).toContain("const [isLoadingRuns, setIsLoadingRuns] = useState(true)");
    expect(source).toContain("Execution history is unavailable. Refresh runtime to try again.");
    expect(source).toContain("No work is currently in progress.");
    expect(source).toContain("No completed executions are recorded.");
  });

  it("does not present unavailable metrics as zero or an unverified approval inbox as empty", () => {
    expect(source).toContain("const [isLoadingApprovals, setIsLoadingApprovals] = useState(true)");
    expect(source).toContain("Loading approval requests…");
    expect(source).toContain("Approval requests are unavailable. Refresh runtime to try again.");
    expect(source).not.toContain("catalog?.total ?? 0");
  });
});


describe("Agent Runtime execution scope isolation", () => {
  it("defaults administrators to personal work and requires explicit tenant selection", () => {
    expect(source).toContain('useState<"personal" | "tenant">("personal")');
    expect(source).toContain('const effectiveScope = canAdminister ? scope : "personal"');
    expect(source).toContain('onClick={() => setScope("tenant")}');
    expect(source).toContain('tenantScope && isAuthenticated');
  });

  it("remounts runtime state when identity or execution scope changes", () => {
    expect(source).toContain('user?.tenant_id, user?.user_id');
    expect(source).toContain('<ScopedAgentsPage key={identity}');
    expect(source).toContain('<AgentRuntimeWorkspace key={effectiveScope}');
  });
});
