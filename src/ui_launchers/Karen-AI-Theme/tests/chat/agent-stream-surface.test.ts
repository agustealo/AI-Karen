import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const apiSource = readFileSync(
  resolve(process.cwd(), "src/lib/api.ts"),
  "utf8",
);

const verifiedRail = readFileSync(
  resolve(process.cwd(), "src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx"),
  "utf8",
);
const verifiedHistory = readFileSync(
  resolve(process.cwd(), "src/components/chat/copilotkit/KarenCopilotVerifiedHistory.tsx"),
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

  it("renders only backend-attested saved agent activity in the canonical context rail", () => {
    expect(verifiedRail).toContain("useKarenLatestVerifiedAgentSteps()");
    expect(verifiedRail).toContain("<ConversationContextRail metadata={receipt} agentSteps={agentSteps}");
    expect(verifiedRail).toContain("No attested agent steps are available");
    expect(verifiedRail).not.toContain("projectObservedAgentSteps");
    expect(verifiedHistory).toContain('name === "karen.agent_step.v1"');
    expect(verifiedHistory).toContain("parseSavedAgentStep(candidate.value)");
    expect(verifiedHistory).toContain("response_source: \"persisted_history\"");
  });
});
