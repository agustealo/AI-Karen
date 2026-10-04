import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const apiSource = readFileSync(
  fileURLToPath(new URL("../../src/lib/api.ts", import.meta.url)),
  "utf8",
);

const chatSource = readFileSync(
  fileURLToPath(
    new URL("../../src/components/chat/ChatInterface.tsx", import.meta.url),
  ),
  "utf8",
);

describe("canonical agent stream surface", () => {
  it("dispatches canonical agent, tool, citation, and approval events", () => {
    expect(apiSource).toContain("case 'agent_step':");
    expect(apiSource).toContain("callbacks?.onAgentStep?.({");
    expect(apiSource).toContain("case 'tool':");
    expect(apiSource).toContain("case 'citation':");
    expect(apiSource).toContain("callbacks?.onCitationBundle?.(citations)");
    expect(apiSource).toContain("case 'approval':");
  });

  it("renders agent activity in the canonical chat surface", () => {
    expect(chatSource).toContain("import AgentActivityPanel from './AgentActivityPanel';");
    expect(chatSource).toContain("<AgentActivityPanel steps={agentSteps} />");
    expect(chatSource).not.toContain("Legacy AgentActivityPanel removed to simplify UI");
  });
});
