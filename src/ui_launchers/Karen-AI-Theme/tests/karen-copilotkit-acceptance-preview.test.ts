import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const page = readFileSync(resolve(root,
  "src/app/acceptance/copilotkit/[conversationId]/page.tsx"), "utf8");
const dashboard = readFileSync(resolve(root, "src/app/dashboard/page.tsx"), "utf8");
const canonicalSessions = readFileSync(resolve(root,
  "src/components/chat/SessionProvider.tsx"), "utf8");
const consumerSource = readFileSync(resolve(root,
  "src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx"), "utf8");
const previewGate = readFileSync(resolve(root,
  "src/app/acceptance/copilotkit/_lib/preview-gate.ts"), "utf8");
const consumerPreview = readFileSync(resolve(root,
  "src/app/acceptance/copilotkit-consumer/[conversationId]/page.tsx"), "utf8");
const prep = readFileSync(resolve(root, "tools/prepare-copilotkit-styles.mjs"), "utf8");
const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const ignore = readFileSync(resolve(root, ".gitignore"), "utf8");
const nativeBrowser = readFileSync(resolve(root,
  "e2e/karen-copilotkit-native-acceptance.spec.ts"), "utf8");
const nextConfig = readFileSync(resolve(root, "next.config.ts"), "utf8");
const browserWorkflow = readFileSync(resolve(root,
  "../../../.github/workflows/karen-history-browser-acceptance.yml"), "utf8");
const shim = readFileSync(resolve(root,
  "src/components/chat/copilotkit/copilotkit-v2-style-import-shim.css"), "utf8");

describe("CK-07E8 isolated native CopilotKit browser acceptance surface", () => {
  it("defaults to a 404 unless both server-only flag and exact host are approved", () => {
    expect(page).toContain("requireApprovedCopilotKitPreview(conversationId)");
    expect(previewGate).toContain('KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED === "true"');
    expect(previewGate).toContain('process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_HOST');
    expect(previewGate).toContain('incomingHost !== allowedHost');
    expect(previewGate).toContain('!APPROVED_HOST.test(allowedHost)');
    expect(previewGate).toContain('!UUID.test(conversationId)');
    expect(page).not.toMatch(/process\\.env\\.NEXT_PUBLIC_[A-Z_]+/);
    expect(page).not.toContain("x-forwarded-host");
  });

  it("mounts the real governed candidate only under authenticated acceptance", () => {
    expect(page).toContain("<AuthWrapper>");
    expect(page).toContain("<KarenCopilotChat conversationId={conversationId} />");
    expect(page).toContain('href="/vendor/copilotkit-v2.css"');
    expect(page).toContain("force-dynamic");
    expect(page).toContain("index: false, follow: false");
    expect(page).not.toContain("new InMemoryAgentRunner");
  });

  it("mounts the canonical consumer candidate on a separately gated preview only", () => {
    expect(consumerPreview).toContain("requireApprovedCopilotKitPreview(conversationId)");
    expect(consumerPreview).toContain("<AuthWrapper>");
    expect(consumerPreview).toContain("<SessionProvider initialSessionId={conversationId} strictInitialSession>");
    expect(consumerPreview).toContain("<KarenCopilotConsumerChat />");
    expect(consumerPreview).toContain('href="/vendor/copilotkit-v2.css"');
    expect(consumerPreview).toContain('index: false, follow: false');
    expect(consumerPreview).not.toContain("process.env.NEXT_PUBLIC_");
    expect(consumerPreview).not.toContain("x-forwarded-host");
    expect(dashboard).not.toContain("<KarenCopilotConsumerChat");
  });

  it("never replaces an unavailable explicitly scoped acceptance conversation", () => {
    expect(canonicalSessions).toContain("strictInitialSession?: boolean");
    expect(canonicalSessions).toContain("strictInitialSession && conversationId !== sessionId");
    expect(canonicalSessions).toContain("if (strictInitialSession) {");
    expect(canonicalSessions).toContain("setCurrentSession(null)");
    expect(canonicalSessions).toContain("No replacement conversation was created.");
    expect(consumerPreview).toContain("strictInitialSession>");
  });

  it("preserves strict errors and does not offer a replacement conversation", () => {
    expect(canonicalSessions).toContain("strictInitialSession: boolean;");
    expect(canonicalSessions).toContain("if (!strictInitialSession) setError(null)");
    expect(canonicalSessions).toContain("if (!strictInitialSession) setError('Failed to load sessions list.");
    expect(consumerSource).toContain("strictInitialSession,");
    expect(consumerSource).toContain("{!strictInitialSession && (");
    expect(consumerSource).toContain("onClick={() => void performNavigation(createNewSession)}");
  });

  it("copies pinned vendor CSS outside the Tailwind v3 PostCSS pipeline", () => {
    expect(prep).toContain('require.resolve("@copilotkit/react-core/package.json")');
    expect(prep).toContain('manifest.exports?.["./v2/styles.css"]');
    expect(prep).toContain('version !== "1.79.1"');
    expect(prep).toContain('source.startsWith(packageRoot + sep)');
    expect(prep).toContain('css.length < 10000');
    expect(prep).not.toContain('import.meta.resolve("@copilotkit/react-core/v2/styles.css")');
    expect(prep).toContain('css.includes("@layer")');
    expect(prep).toContain('"vendor", "copilotkit-v2.css"');
    expect(pkg.scripts.dev).toContain("prepare-copilotkit-styles.mjs");
    expect(pkg.scripts.build).toContain("prepare-copilotkit-styles.mjs");
    expect(ignore).toContain("/public/vendor/copilotkit-v2.css");
    expect(page).not.toContain('import "@copilotkit/react-core/v2/styles.css"');
  });

  it("intercepts only the SDK-internal compiled v4 stylesheet at the webpack boundary", () => {
    expect(nextConfig).toContain("new webpack.NormalModuleReplacementPlugin");
    expect(nextConfig).toContain("resource.context");
    expect(nextConfig).toContain("resource.request");
    expect(nextConfig).toContain("@copilotkit");
    expect(nextConfig).toContain("react-core");
    expect(nextConfig).toContain("dist");
    expect(nextConfig).toContain("copilotkit-v2-style-import-shim.css");
    expect(nextConfig).not.toContain("postcss: false");
    expect(shim.trim()).toBe("/* CopilotKit v2 CSS is loaded from the approved local static asset. */");
  });

  it("proves canonical cross-tab CAS and mobile read-only acceptance without model sends", () => {
    expect(nativeBrowser).toContain("page.context().newPage()");
    expect(nativeBrowser).toContain("expected_revision: revision");
    expect(nativeBrowser).toContain("karen-copilot-unsynced-draft");
    expect(nativeBrowser).toContain("Reload saved draft (discard local changes)");
    expect(nativeBrowser).toContain("page.setViewportSize({ width: 375, height: 812 })");
    expect(nativeBrowser).toContain('"/api/personas/preferences/me"');
    expect(nativeBrowser).toContain('trace: "off", screenshot: "off", video: "off"');
    expect(nativeBrowser).toContain("expect(runs");
    expect(nativeBrowser).toContain("isInferenceRequest(request.url())");
    expect(nativeBrowser).toContain('pathname === "/api/chat/ag-ui"');
    expect(nativeBrowser).toContain('pathname === "/api/chat/stream"');
    expect(nativeBrowser).toContain("grantPermissions([], { origin })");
    expect(nativeBrowser).toContain('name: "Start local dictation"');
    expect(nativeBrowser).toContain('path.startsWith("/api/voice/")');
    expect(nativeBrowser).toContain("savedBefore");
    expect(nativeBrowser).toContain("KAREN_COPILOTKIT_PERSONA_MUTATION_REQUIRED");
    expect(nativeBrowser).toContain("expected_revision: value.revision");
    expect(nativeBrowser).toContain("Persona restoration must be CAS-confirmed");
    expect(nativeBrowser).toContain("CK-07F rejects runless and nonexistent stop requests");
    expect(nativeBrowser).toContain('"ck07_absent_" + crypto.randomUUID()');
    expect(nativeBrowser).toContain("runless.status()).toBe(422)");
    expect(nativeBrowser).toContain("unknown.status()");
    expect(nativeBrowser).toContain("toEqual(history)");
    expect(nativeBrowser).toContain("KAREN_COPILOTKIT_LIVE_STOP_REQUIRED");
    expect(nativeBrowser).toContain('test.skip(!enabled, "Real model cancellation requires an approved disposable conversation")');
    expect(nativeBrowser).toContain("KAREN_COPILOTKIT_LIVE_STOP_CONVERSATION_ID");
    expect(nativeBrowser).toContain("Read-only canonical run status must be available");
    expect(nativeBrowser).toContain('"not-admitted"');
    expect(nativeBrowser).toContain("Canonical run status must be readable");
    expect(nativeBrowser).toContain('Native Stop must target exactly one observed run');
    expect(nativeBrowser).toContain('getByTestId("karen-copilot-sdk-chat")');
    expect(nativeBrowser).toContain("Require one and only one SDK inference Stop");
    expect(nativeBrowser).not.toContain('native.getByRole("button", { name: /stop/i }).first()');
    expect(nativeBrowser).toContain('runId: payload.runId');
    expect(nativeBrowser).toContain("Cancelled run must not create a falsely completed");
  });

  it("dispatches consumer acceptance through the existing protected exact-SHA browser workflow", () => {
    expect(browserWorkflow).toContain("- copilotkit-consumer");
    expect(browserWorkflow).toContain("inputs.scenario == 'copilotkit-consumer'");
    expect(browserWorkflow).toContain("Require the current reviewed main commit before checkout");
    expect(browserWorkflow).toContain("Verify deployed revision before browser acceptance");
    expect(browserWorkflow).toContain("Verify independent Vercel deployment provenance before browser acceptance");
    expect(browserWorkflow).toContain("KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED:");
    expect(browserWorkflow).toContain("--grep 'CK-CONSUMER-0[12]'");
    expect(browserWorkflow).toContain("Revalidate platform, running deployment and reviewed main head after browser acceptance");
    expect(nativeBrowser).toContain('test("CK-CONSUMER-01 gated consumer preview restores an owned session without inference"');
    expect(nativeBrowser).toContain('test("CK-CONSUMER-02 unavailable scoped conversation cannot become a new thread"');
  });

  it("does not disturb the sole consumer chat mount", () => {
    expect(dashboard).toContain("<KarenAssistantChat />");
    expect(dashboard).not.toContain("<KarenCopilotChat");
    expect(dashboard.match(/<KarenAssistantChat \/>/g)?.length).toBe(1);
  });
});
