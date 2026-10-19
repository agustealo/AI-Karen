import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const component = readFileSync(
  resolve(process.cwd(), "src/components/chat/assistant-ui/KarenAssistantChat.tsx"),
  "utf8",
);
const dashboard = readFileSync(
  resolve(process.cwd(), "src/app/dashboard/page.tsx"),
  "utf8",
);
const packageJson = JSON.parse(
  readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
);

describe("governed assistant-ui AG-UI chat boundary", () => {
  it("uses the official AG-UI runtime with a same-origin canonical proxy", () => {
    expect(component).toContain("useAgUiRuntime({");
    expect(component).toContain('new HttpAgent({ url: "/api/chat/ag-ui" })');
    expect(component).toContain("AssistantRuntimeProvider");
    expect(component).toContain("ThreadPrimitive.Messages");
    expect(component).toContain("ComposerPrimitive.Input");
    expect(component).toContain("ComposerPrimitive.Cancel");
    expect(component).toContain("ComposerPrimitive.Send");
    expect(packageJson.dependencies["@assistant-ui/react"]).toBeDefined();
    expect(packageJson.dependencies["@assistant-ui/react-ag-ui"]).toBeDefined();
    expect(packageJson.dependencies["@ag-ui/client"]).toBeDefined();
  });

  it("reuses the existing durable conversation owner and allows no local fake persistence", () => {
    expect(dashboard).toContain("<SessionProvider>");
    expect(dashboard).toContain("USE_ASSISTANT_UI_CHAT ? <KarenAssistantChat /> : <ChatInterface />");
    expect(component).toContain('import { useSession } from "@/components/chat/ChatInterface"');
    expect(component).toContain("/api/conversations/");
    expect(component).toContain("ExportedMessageRepository.fromArray");
    expect(component).toContain("fromAgUiMessages");
    expect(component).toContain("threadId,");
    expect(component).not.toContain("localStorage.setItem");
    expect(component).not.toContain("selectedModel");
    expect(component).not.toContain("setSelectedProvider");
  });

  it("only exposes backend-observed data parts and does not invent resume or tool execution", () => {
    expect(component).toContain("agui-activity/KAREN_AGENT_STEP");
    expect(component).toContain("agui-activity/KAREN_DEEPAGENTS_PLAN");
    expect(component).toContain("agui-activity/KAREN_DEEPAGENTS_SUBAGENT");
    expect(component).toContain("karen.learning_decision");
    expect(component).toContain("karen.checkpoint");
    expect(component).toContain("karen.approval_required");
    expect(component).toContain("No resume action is available");
    expect(component).toContain("No action will execute from this informational notice");
    expect(component).not.toContain("useAgUiSetState");
    expect(component).not.toContain("addToolResult");
    expect(component).not.toContain("autoApprove");
  });

  it("exposes only persisted conversation history and observed expandable activity", () => {
    expect(component).toContain('id="karen-history-search"');
    expect(component).toContain("matchingSessions.map((session)");
    expect(component).toContain("loadSession(session.id)");
    expect(component).toContain('aria-expanded={historyOpen}');
    expect(component).toContain("historySearchRef.current?.focus()");
    expect(component).toContain('event.key === "Escape"');
    expect(component).toContain("historyTriggerRef.current?.focus()");
    expect(component).toContain('<details data-testid="karen-agent-activity"');
    expect(component).toContain("defaultOpen={failed}");
    expect(component).toContain('<details data-testid="karen-learning-provenance"');
    expect(component).toContain('<details data-testid="karen-checkpoint-evidence"');
    expect(component).toContain("value.stepId");
    expect(component).not.toContain("localStorage.setItem");
    expect(component).not.toContain("clientExecuteTool");
  });

  it("keeps the adapter opt-in until backend and npm dependency proof pass", () => {
    expect(dashboard).toContain(
      'process.env.NEXT_PUBLIC_KAREN_ASSISTANT_UI_ENABLED === "true"',
    );
    expect(dashboard).toContain('{ ssr: false }');
    expect(component).toContain("showThinking: false");
  });
});
