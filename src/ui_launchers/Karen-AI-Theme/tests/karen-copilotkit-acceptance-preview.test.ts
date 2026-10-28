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

  it("does not disturb the sole consumer chat mount", () => {
    expect(dashboard).toContain("<KarenAssistantChat />");
    expect(dashboard).not.toContain("<KarenCopilotChat");
    expect(dashboard.match(/<KarenAssistantChat \/>/g)?.length).toBe(1);
  });
});
