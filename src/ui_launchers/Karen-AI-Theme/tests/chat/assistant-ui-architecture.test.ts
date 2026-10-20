import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const component = readFileSync(
  resolve(process.cwd(), "src/components/chat/assistant-ui/KarenAssistantChat.tsx"),
  "utf8",
);
const legacyChat = readFileSync(resolve(process.cwd(), "src/components/chat/ChatInterface.tsx"), "utf8");
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

  it("reuses official assistant-ui copy controls without unauthorized retry or edit", () => {
    expect(component).toContain("ActionBarPrimitive.Root");
    expect(component).toContain("ActionBarPrimitive.Copy");
    expect(component).toContain('aria-label="Copy message"');
    expect(component).toContain("group-data-[copied]/copy:inline");
    expect(component).toContain("<KarenCopyAction />");
    expect(component).not.toContain("ActionBarPrimitive.Reload");
    expect(component).not.toContain("ActionBarPrimitive.Edit");
  });

  it("renders assistant text as safe GitHub-flavored Markdown without an HTML escape hatch", () => {
    expect(component).toContain('import ReactMarkdown from "react-markdown"');
    expect(component).toContain('import remarkGfm from "remark-gfm"');
    expect(component).toContain('Text: KarenMarkdownText');
    expect(component).toContain('skipHtml');
    expect(component).toContain('urlTransform={(url) => /^(https?:|mailto:)/i.test(url) ? url : ""}');
    expect(component).not.toContain('rehypeRaw');
    expect(component).not.toContain('dangerouslySetInnerHTML');
  });

  it("renders fenced code in a scrollable region with accessible copy and truthful clipboard state", () => {
    expect(component).toContain("function KarenCodeBlock");
    expect(component).toContain("components={{ pre: KarenCodeBlock }}");
    expect(component).toContain('aria-label={copied ? "Code copied" : "Copy code block"}');
    expect(component).toContain("await navigator.clipboard.writeText(source)");
    expect(component).toContain("setCopied(false)");
    expect(component).toContain("overflow-x-auto");
    expect(component).not.toContain("dangerouslySetInnerHTML");
  });

  it("keeps Web Speech constructor typing scoped instead of conflicting with browser globals", () => {
    expect(legacyChat).toContain("const speechWindow = window as unknown as {");
    expect(legacyChat).not.toContain("declare global {\\n  interface Window {\\n    SpeechRecognition");
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

  it("never calls React hooks conditionally for malformed activity events", () => {
    const activity = component.slice(component.indexOf("function KarenActivity("), component.indexOf("function KarenLearningDecision("));
    expect(activity.indexOf("const disclosureRef = useRef")).toBeLessThan(activity.indexOf("if (!data || typeof data !=="));
    expect(activity.indexOf("useEffect(() =>")).toBeLessThan(activity.indexOf("if (!data || typeof data !=="));
  });

  it("does not interpret unknown agent statuses as successful execution", () => {
    expect(component).toContain('["failed", "failure", "error", "errored", "cancelled", "canceled"].includes(normalized)');
    expect(component).toContain('["finished", "completed", "complete", "succeeded", "success"].includes(normalized)');
    expect(component).not.toContain('normalized.includes("success")');
    expect(component).not.toContain('normalized.includes("complete")');
  });

  it("renders runtime-supplied event provenance without fabricating task ordering", () => {
    expect(component).toContain('typeof value.runId === "string"');
    expect(component).toContain('typeof value.eventId === "string"');
    expect(component).toContain('Number.isNaN(Date.parse(rawTimestamp))');
    expect(component).toContain('typeof fields.run_id === "string"');
    expect(component).toContain('typeof fields.event_id === "string"');
    expect(component).toContain('typeof fields.step_id === "string"');
    expect(component).toContain('AG-UI run: {runId}');
    expect(component).toContain('Event: {eventId}');
    expect(component).toContain('Reported: {reportedAt}');
    expect(component).not.toContain('Date.now()');
    expect(component).not.toContain('fakeTimeline');
  });

  it("labels observed plans, subagents and steps without adding an execution path", () => {
    expect(component).toContain('"agui-activity/KAREN_AGENT_STEP": KarenAgentStep');
    expect(component).toContain('"agui-activity/KAREN_DEEPAGENTS_PLAN": KarenAgentPlan');
    expect(component).toContain('"agui-activity/KAREN_DEEPAGENTS_SUBAGENT": KarenSubagent');
    expect(component).toContain('category="Plan"');
    expect(component).toContain('category="Subagent"');
    expect(component).toContain('Reported status:');
    expect(component).not.toContain("executeSubagent(");
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
    expect(component).toContain("onClick={() => void switchConversation(session.id)}");
    expect(component).toContain('aria-expanded={historyOpen}');
    expect(component).toContain("historySearchRef.current?.focus()");
    expect(component).toContain('event.key === "Escape"');
    expect(component).toContain("historyTriggerRef.current?.focus()");
    expect(component).toContain("await loadSession(id)");
    expect(component).toContain("await createNewSession()");
    expect(component).toContain("Unable to open that conversation.");
    expect(component).toContain("Unable to create a conversation.");
    expect(component).toContain('{navigationError && <p role="alert"');
    expect(component).toContain('data-testid="karen-agent-activity"');
    expect(component).toContain("ref={disclosureRef}");
    expect(component).toContain("disclosureRef.current.open = true");
    expect(component).not.toContain("open={failed || undefined}");
    expect(component).toContain('<details data-testid="karen-learning-provenance"');
    expect(component).toContain('<details data-testid="karen-checkpoint-evidence"');
    expect(component).toContain("value.stepId");
    expect(component).not.toContain("localStorage.setItem");
    expect(component).toContain('data-testid="karen-observed-tool"');
    expect(component).toContain("Only Karen&apos;s governed execution receipt");
    expect(component).toContain("It does not confirm that an external action succeeded.");
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

describe("Agent Runtime original-conversation handoff", () => {
  it("uses shared SessionProvider rather than a new chat provider", () => {
    expect(dashboard).toContain("function AgentWorkspaceView");
    expect(dashboard).toContain("const { loadSession } = useSession()");
    expect(dashboard).toContain("await loadSession(conversationId)");
    expect(dashboard).toContain("onOpenConversation={openConversation}");
    expect(dashboard).not.toContain("<AgentsPage onAskKaren={() => setActiveMainView");
  });
});

describe("persistent Karen workspace panel", () => {
  it("keeps exactly one mounted chat and presents it across dashboard workspaces", () => {
    expect(dashboard).toContain('data-testid="persistent-karen-conversation"');
    expect(dashboard).toContain("karenPanelOpen");
    expect(dashboard).toContain('aria-label="Collapse Karen conversation"');
    expect(dashboard).toContain('aria-controls="persistent-karen-panel"');
    expect(dashboard.match(/<KarenAssistantChat \/>/g)?.length).toBe(1);
    expect(dashboard.match(/<ChatInterface \/>/g)?.length).toBe(1);
    expect(dashboard).toContain("backendStatus === \"ready\" && (activeMainView === \"chat\" || karenPanelOpen)");
  });
});
