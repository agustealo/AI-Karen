import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = (path: string) =>
  readFileSync(resolve(process.cwd(), path), "utf8");

describe("canonical CopilotKit conversation intelligence restoration", () => {
  it("mounts exactly one verified intelligence rail per owned SDK conversation", () => {
    const shell = source("src/components/chat/copilotkit/KarenCopilotChat.tsx");
    const rail = source("src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx");
    const history = source("src/components/chat/copilotkit/KarenCopilotHistoryGate.tsx");

    expect(shell).toContain("<KarenCopilotHistoryGate conversationId={conversationId}");
    expect(shell).toContain("onStartNewConversation={onStartNewConversation}");
    expect(shell).toContain("<KarenCopilotVerifiedRail />");
    expect(shell.match(/<KarenCopilotVerifiedRail \/>/g)).toHaveLength(1);
    expect(rail).toContain("useKarenVerifiedResponseContext()");
    expect(rail).toContain("metadata={selected.receipt}");
    expect(rail).toContain("agentSteps={selected.agentSteps}");
    expect(rail).toContain("renderPresentations()");
    expect(rail).toContain("<RailUnavailable embedded />");
    expect(rail).toContain("<ActivityReplayNotice />");
    expect(rail).toContain("No attested agent steps are available for the selected saved assistant turn.");
    expect(history).toContain("parseKarenVerifiedHistory(");
    expect(history).toContain("agent.setMessages(messages)");
    expect(history).toContain("snapshot.threadId !== conversationId");
  });

  it("does not manufacture agent steps from an SDK state projection", () => {
    const rail = source("src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx");
    expect(rail).not.toContain("projectObservedAgentSteps");
    expect(rail).not.toContain("state.thread.messages");
    expect(rail).toContain("useKarenVerifiedResponseContext()");
    expect(rail).not.toContain("agentSteps={[]}");
  });
});
