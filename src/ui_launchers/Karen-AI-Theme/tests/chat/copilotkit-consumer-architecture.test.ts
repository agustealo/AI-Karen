import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (relative: string): string =>
  readFileSync(resolve(process.cwd(), relative), "utf8");

const dashboard = read("src/app/dashboard/page.tsx");
const consumer = read("src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx");
const shell = read("src/components/chat/copilotkit/KarenCopilotChat.tsx");
const controller = read("src/components/chat/copilotkit/KarenCopilotControlledChat.tsx");
const history = read("src/components/chat/copilotkit/KarenCopilotHistoryGate.tsx");
const verified = read("src/components/chat/copilotkit/KarenCopilotVerifiedHistory.tsx");
const rail = read("src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx");
const session = read("src/components/chat/SessionProvider.tsx");
const catalog = read("src/components/chat/KarenComposerRuntimeCatalog.tsx");
const pkg = JSON.parse(read("package.json"));
const liveBrowser = read("e2e/copilotkit-consumer-boot.spec.ts");
const nativePreview = read("src/app/acceptance/copilotkit/[conversationId]/page.tsx");
const consumerPreview = read("src/app/acceptance/copilotkit-consumer/[conversationId]/page.tsx");

const draftHook = read("src/components/chat/copilotkit/useKarenPersistedDraft.ts");

describe("canonical CopilotKit chat ownership", () => {
  it("puts consumer language first and defers technical inventory", () => {
    expect(consumer).toContain("What would you like to work on?");
    expect(consumer).toContain("Your space to think, create, and get things done");
    expect(consumer).toContain("Model preferences");
    expect(consumer).not.toContain("Karen runtime controls model execution and saved history");
    expect(catalog).toContain("Automatic lets Karen choose an available model.");
    expect(catalog).toContain("Advanced provider and agent details");
    expect(catalog).toContain("if (!showAdvanced) return;");
    expect(catalog).toContain("showAdvanced && <div");
  });


  it("preserves unsent text and keeps destructive draft recovery secondary", () => {
    expect(controller).toContain('aria-label="Draft recovery"');
    expect(controller).toContain('value={draft} onChange={event => setDraftText(event.target.value)}');
    expect(controller).toContain("Copy unsent text");
    expect(controller).toContain("Reconnect and save");
    expect(controller).toContain("<details");
    expect(controller).toContain("Discard local changes and reload saved draft");
    expect(controller).toContain('draftStatus === "conflict" || draftStatus === "unavailable"');
    expect(draftHook).toContain("failureStatus");
    expect(draftHook).toContain("error instanceof ApiError ? error.status : null");
    expect(draftHook).toContain("revisionRef.current === null");
  });


  it("has exactly one dashboard renderer and no old assistant-ui import", () => {
    expect(dashboard.match(/<KarenCopilotConsumerChat onOpenAgents=\{\(\) => setActiveMainView\("agents"\)\} \/>/g)).toHaveLength(1);
    expect(dashboard).not.toContain("<KarenAssistantChat");
    expect(dashboard).not.toContain("@/components/chat/assistant-ui/KarenAssistantChat");
    expect(dashboard).toContain("<PrincipalScopedSessionProvider>");
    expect(dashboard).toContain("<SessionProvider storagePrincipal={{");
    expect(dashboard).toContain("tenant_id: user.tenant_id");
    expect(dashboard).toContain("user_id: user.user_id");
    expect(dashboard).toContain('data-testid="persistent-karen-conversation"');
  });

  it("loads CopilotKit CSS from the real shared chat shell, not from previews alone", () => {
    expect(shell).toContain('<link rel="stylesheet" href="/vendor/copilotkit-v2.css" />');
    expect(shell).toContain('enableInspector={false}');
    expect(dashboard).toContain('<KarenCopilotConsumerChat onOpenAgents={() => setActiveMainView("agents")} />');
    expect(nativePreview).not.toContain('href="/vendor/copilotkit-v2.css"');
    expect(consumerPreview).not.toContain('href="/vendor/copilotkit-v2.css"');
    expect(liveBrowser).toContain("await expectRealCopilotKitStyles(page)");
    expect(liveBrowser).toContain('link.sheet.cssRules.length > 0');
  });

  it("verifies persisted messages through the real browser's bearer and cookie context", () => {
    expect(liveBrowser).toContain("readAuthorizedSameOriginJson(page, draftEndpoint)");
    expect(liveBrowser).toContain("readAuthorizedSameOriginJson(page, endpoint)");
    expect(liveBrowser).toContain('window.localStorage.getItem("access_token")');
    expect(liveBrowser).toContain('credentials: "same-origin"');
    expect(liveBrowser).toContain('redirect: "error"');
    expect(liveBrowser).toContain('url.origin !== window.location.origin');
    expect(liveBrowser).not.toContain("authenticatedRequest.get");
  });

  it("requires a live non-cacheable backend before approved browser sign-in", () => {
    const preflight = "await requireLiveCanonicalBackend(page, target);";
    expect(liveBrowser.split(preflight)).toHaveLength(3);
    const firstSignIn = liveBrowser.indexOf("await signInApprovedKaren(page, approvedEmail!, approvedPassword!)");
    const secondSignIn = liveBrowser.lastIndexOf("await signInApprovedKaren(page, approvedEmail!, approvedPassword!)");
    const firstCheck = liveBrowser.indexOf(preflight);
    const secondCheck = liveBrowser.lastIndexOf(preflight);
    expect(firstCheck).toBeLessThan(firstSignIn);
    expect(secondCheck).toBeLessThan(secondSignIn);
    expect(liveBrowser).toContain("backend_ready: true");
    expect(liveBrowser).toContain('new URL("/api/health", target)');
    expect(liveBrowser).toContain("maxRedirects: 0");
    expect(liveBrowser).toContain('response.headers()["cache-control"] ?? ""');
    expect(liveBrowser).toContain('expectVerifiedExecutionReceipt(page, id!, persistedAnswer)');
  });

  it("uses the governed runtime, canonical session and verified history", () => {
    expect(consumer).toContain("useSession()");
    expect(consumer).toContain("<KarenCopilotChat");
    expect(consumer).toContain("workspaceRunId={workspaceRunId}");
    expect(shell).toContain('runtimeUrl="/api/copilotkit"');
    expect(shell).toContain("<KarenCopilotHistoryGate conversationId={conversationId}>");
    expect(shell).toContain("<KarenCopilotVerifiedRail />");
    expect(history).toContain("parseKarenVerifiedHistory(");
    expect(history).toContain("agent.setMessages(messages)");
    expect(history).toContain("snapshot.threadId !== conversationId");
    expect(session).toContain("workspaceRunId: string | null");
  });

  it("registers a scoped SDK agent from one canonical owner only", () => {
    expect(history).toContain("const registration = useAgent({");
    expect(history).toContain("ScopedAgentContext.Provider value={registration}");
    expect(history).toContain("export function useKarenScopedAgent()");
    expect(controller).toContain("const { agent, isReady } = useKarenScopedAgent()");
    expect(controller).not.toContain("useAgent(");
    expect(controller).not.toContain("registerProxiedAgent");
  });

  it("requires explicit submission, backend stop receipts and durable draft clearance", () => {
    expect(controller).toContain("clearBeforeSubmit(text)");
    expect(controller).toContain("copilotkit.runAgent({ agent })");
    expect(controller).toContain("validStopReceipt(receipt)");
    expect(controller).toContain("copilotkit.stopAgent({ agent })");
    expect(controller).toContain("KarenLocalDictationCapture");
    expect(controller).toContain("KarenBrowserDictationCapture");
    expect(controller).not.toContain("@assistant-ui/");
  });

  it("renders verified receipts and no invented historical agent activity", () => {
    expect(verified).toContain("parseKarenVerifiedHistory");
    expect(verified).toContain("KarenRestoredExecutionReceipt");
    expect(rail).toContain("useKarenLatestVerifiedExecution()");
    expect(rail).toContain("useKarenLatestVerifiedAgentSteps()");
    expect(rail).not.toContain("agentSteps={[]}");
    expect(rail).toContain("No attested agent steps are available for the latest saved assistant turn.");
    expect(rail).not.toContain("projectObservedAgentSteps");
  });

  it("retains canonical agent workspace handoff and model discovery", () => {
    expect(dashboard).toContain("function AgentWorkspaceView");
    expect(dashboard).toContain("setWorkspaceRunId(runId); openChat()");
    expect(catalog).toContain('"/api/agent-runtime/catalog"');
    expect(catalog).toContain("Discovery only.");
    expect(catalog).not.toContain("executeAgent(");
  });

  it("rejects assistant-ui packages after renderer retirement", () => {
    expect(pkg.dependencies["@copilotkit/react-core"]).toBe("1.79.1");
    expect(pkg.dependencies["@assistant-ui/react"]).toBeUndefined();
    expect(pkg.dependencies["@assistant-ui/react-ag-ui"]).toBeUndefined();
    expect(pkg.dependencies["@ag-ui/client"]).toBe("1.0.2");
  });
});
