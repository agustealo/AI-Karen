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
    expect(source).toContain("Chat remains the execution entry point");
    expect(source).toContain("CORTEX decides");
    expect(source).toContain("RuntimePolicy authorizes");
    expect(source).toContain("Per-agent daemon");
  });
});
