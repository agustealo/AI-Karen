import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("canonical assistant-ui rail restoration", () => {
  it("uses the existing intelligence rail beside a single mounted AG-UI conversation", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/components/chat/assistant-ui/KarenAssistantChat.tsx"),
      "utf8",
    );
    expect(source).toContain('import ConversationContextRail from "@/components/chat/ConversationContextRail"');
    expect(source).toContain('<KarenAgUiRuntime key={currentSession.id} threadId={currentSession.id} />');
    expect(source).toContain('<ConversationContextRail metadata={{}} agentSteps={[]} />');
    expect(source.match(/<KarenAgUiRuntime key=/g)).toHaveLength(1);
  });
});
