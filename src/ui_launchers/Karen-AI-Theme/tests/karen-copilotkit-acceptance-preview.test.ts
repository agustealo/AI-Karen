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
    expect(page).not.toContain("NEXT_PUBLIC_");
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

  it("does not disturb the sole consumer chat mount", () => {
    expect(dashboard).toContain("<KarenAssistantChat />");
    expect(dashboard).not.toContain("<KarenCopilotChat");
    expect(dashboard.match(/<KarenAssistantChat \/>/g)?.length).toBe(1);
  });
});
