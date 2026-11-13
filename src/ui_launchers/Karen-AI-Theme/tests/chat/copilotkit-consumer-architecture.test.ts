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
    expect(controller).toContain('input={{ value: draft, onChange: onDraftChange, onSubmitMessage, onStop }}');
    expect(controller).toContain('{recoveryPanel}');
    expect(controller).not.toContain('karen-unsynced-draft');
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

  it("captures only redacted first-send failure provenance in the existing real browser suite", () => {
    expect(liveBrowser).toContain('"kcon490-first-send-failure-receipt"');
    expect(liveBrowser).toContain('schema: "karen.first_send_failure.v1"');
    expect(liveBrowser).toContain('run_http_responses: observedRunResponses.slice(-8)');
    expect(liveBrowser).toContain('run_transport_failures: observedRunTransportFailures.slice(-8)');
    expect(liveBrowser).toContain('draft_cas: draftCas.slice(-8)');
    expect(liveBrowser).toContain('composer_alert_visible: alertVisible');
    expect(liveBrowser).toContain('persisted_assistant_confirmed: false');
    expect(liveBrowser).toContain('correlation_id: /^[A-Za-z0-9_-]{1,128}$/.test(header) ? header : null');
    expect(liveBrowser).toContain('throw error;');
    // No raw request/response bodies, user text, credentials or full URLs in
    // acceptance attachments. They are disabled for public CI.
    expect(liveBrowser).not.toContain('postDataJSON()\n      });');
    expect(liveBrowser).not.toContain('testInfo.attach("chat-transcript"');
    expect(liveBrowser).not.toContain('testInfo.attach("authorization"');
  });

  it("keeps multi-turn personal-context proof in the real governed browser path", () => {
    expect(liveBrowser).toContain(
      'const personalContextAcceptance = process.env.KAREN_PERSONAL_CONTEXT_ACCEPTANCE === "1";',
    );
    expect(liveBrowser).toContain(
      'await test.step("KCON-490 real multi-turn personal context", async () => {',
    );
    expect(liveBrowser).toContain('await runPersonalTurn("ANything else?")');
    expect(liveBrowser).toContain(
      '"Yeah like my favorite color, or whatever you can share"',
    );
    expect(liveBrowser).toContain(
      '"I am a vegetarian, and I love dancehall music, it is my favorite genre"',
    );
    expect(liveBrowser).toContain('await expectVerifiedExecutionReceipt(page, id!, expansion)');
    expect(liveBrowser).toContain('await expectVerifiedExecutionReceipt(page, id!, disclosure)');
    expect(liveBrowser).toContain('expect(observedRunRequests.length - initialRunCount).toBe(6)');
    expect(liveBrowser).toContain('const final = await readAuthorizedSameOriginJson(page, endpoint)');
    // Existing first-send authentication, revision and health preflights
    // remain the only authority to run this opt-in multi-turn extension.
    expect(liveBrowser).toContain('if (personalContextAcceptance && !enabled)');
    expect(liveBrowser).toContain('if (personalContextAcceptance && kcon770FaultAcceptance)');
    expect(liveBrowser).toContain('trace: "off"');
    expect(liveBrowser).toContain('screenshot: "off"');
    expect(liveBrowser).toContain('video: "off"');
    expect(liveBrowser).not.toContain('testInfo.attach("kcon490-personal-transcript"');
  });

  it("requires a live non-cacheable backend before approved browser sign-in", () => {
    // Each independent real-browser scenario must verify backend readiness
    // before credentials are used. Do not hardcode the number of scenarios:
    // new time/weather acceptance must increase coverage without weakening auth.
    const preflights = [...liveBrowser.matchAll(/await requireLiveCanonicalBackend\(page, target\);/g)]
      .map(match => match.index!);
    const signIns = [...liveBrowser.matchAll(/await signInApprovedKaren\(page, approvedEmail!, approvedPassword!, \{ allowLocalLoopback: localMode \}\);/g)]
      .map(match => match.index!);
    expect(preflights.length).toBeGreaterThanOrEqual(2);
    expect(preflights).toHaveLength(signIns.length);
    preflights.forEach((position, index) => {
      expect(position).toBeLessThan(signIns[index]);
      if (index > 0) {
        expect(position).toBeGreaterThan(signIns[index - 1]);
      }
    });
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
    expect(shell).toContain("<KarenCopilotHistoryGate conversationId={conversationId}");
    expect(shell).toContain("onStartNewConversation={onStartNewConversation}");
    expect(shell).toContain("<KarenCopilotVerifiedRail />");
    expect(history).toContain("parseKarenVerifiedHistory(");
    expect(history).toContain("agent.setMessages(messages)");
    expect(history).toContain("snapshot.threadId !== conversationId");
    expect(session).toContain("workspaceRunId: string | null");
  });

  it("externalizes only the Node-side CopilotKit runtime dynamic loader", () => {
    const nextConfig = read("next.config.ts");
    const route = read("src/app/api/copilotkit/[[...slug]]/route.ts");
    const packageInfo = JSON.parse(read("package.json"));

    // The 1.79.1 server SDK imports channel-manager.mjs, whose dynamic
    // require is not statically resolvable by the Webpack app-route bundle.
    // Next 15's public API keeps only this server package on native Node
    // resolution; the browser SDK and app router remain bundle-owned.
    expect(packageInfo.dependencies["@copilotkit/runtime"]).toBe("1.79.1");
    expect(nextConfig).toContain("serverExternalPackages: ['@copilotkit/runtime']");
    expect(nextConfig).not.toContain("serverExternalPackages: ['@copilotkit/react-core']");
    expect(nextConfig).not.toContain("ignoreWarnings");
    expect(route).toContain('export const runtime = "nodejs";');
    expect(route).toContain('await import("@copilotkit/runtime/v2")');
    expect(route.indexOf("COPILOTKIT_TELEMETRY_DISABLED")).toBeLessThan(
      route.indexOf('await import("@copilotkit/runtime/v2")'),
    );
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
    expect(controller).toContain("prepareSubmission(text)");
    expect(draftHook).toContain("return clearBeforeSubmit(submittedText)");
    expect(draftHook).toContain("await startSave()");
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
