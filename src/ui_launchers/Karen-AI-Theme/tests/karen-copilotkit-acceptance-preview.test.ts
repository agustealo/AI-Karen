import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const page = readFileSync(resolve(root,
  "src/app/acceptance/copilotkit/[conversationId]/page.tsx"), "utf8");
const dashboard = readFileSync(resolve(root, "src/app/dashboard/page.tsx"), "utf8");
const prep = readFileSync(resolve(root, "tools/prepare-copilotkit-styles.mjs"), "utf8");
const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const ignore = readFileSync(resolve(root, ".gitignore"), "utf8");
const nativeBrowser = readFileSync(resolve(root,
  "e2e/karen-copilotkit-native-acceptance.spec.ts"), "utf8");
const nextConfig = readFileSync(resolve(root, "next.config.ts"), "utf8");
const shim = readFileSync(resolve(root,
  "src/components/chat/copilotkit/copilotkit-v2-style-import-shim.css"), "utf8");

describe("CK-07E8 isolated native CopilotKit browser acceptance surface", () => {
  it("defaults to a 404 unless both server-only flag and exact host are approved", () => {
    expect(page).toContain('KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED === "true"');
    expect(page).toContain('process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_HOST');
    expect(page).toContain('incomingHost !== allowedHost');
    expect(page).toContain('if (!enabled || !APPROVED_HOST.test(allowedHost)) notFound()');
    expect(page).toContain('if (!UUID.test(conversationId)) notFound()');
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

  it("copies pinned vendor CSS outside the Tailwind v3 PostCSS pipeline", () => {
    expect(prep).toContain('import.meta.resolve("@copilotkit/react-core/v2/styles.css")');
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
  });

  it("does not disturb the sole consumer chat mount", () => {
    expect(dashboard).toContain("<KarenAssistantChat />");
    expect(dashboard).not.toContain("<KarenCopilotChat");
    expect(dashboard.match(/<KarenAssistantChat \/>/g)?.length).toBe(1);
  });
});
