import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const apiSource = readFileSync(
  resolve(process.cwd(), "src/lib/api.ts"),
  "utf8",
);

const chatSource = readFileSync(
  resolve(process.cwd(), "src/components/chat/assistant-ui/KarenAssistantChat.tsx"),
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
    expect(chatSource).toContain("function KarenActivity(");
    expect(chatSource).toContain('<KarenActivity data={data} category="Agent step" />');
    expect(chatSource).toContain("MessagePrimitive.Parts");
  });
});
