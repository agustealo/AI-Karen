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
    expect(source).toContain('<ConversationContextRail metadata={loadState === "ready" ? metadata : {}} agentSteps={observedSteps} />');
    expect(source).toContain('projectObservedAgentSteps(observedMessages)');
    expect(source).toContain('state.thread.messages');
    expect(source).toContain('part.type !== "data"');
    expect(source).toContain('message.role !== "assistant"');
    expect(source).toContain('new Map<string, AgentStepEvent>()');
    expect(source).toContain('messages[messages.length - 1]');
    expect(source).toContain('for (const rawMessage of activeMessages)');
    expect(source).not.toContain('messages.slice(-60)');
    expect(source).not.toContain('agentSteps={[]}');
    expect(source).toContain('setLoadState("empty")');
    expect(source).toContain('setMetadata({});');
    expect(source).toContain('(message) => message.role === "assistant",');
    expect(source).not.toContain('(message) => message.role === "assistant" && message.metadata,');
    expect(source).toContain('encodeURIComponent(threadId)');
    expect(source).toContain('<KarenConversationIntelligence threadId={threadId} />');
    expect(source).toContain('conversation.id !== threadId');
    expect(source.match(/<KarenAgUiRuntime key=/g)).toHaveLength(1);
  });
});
