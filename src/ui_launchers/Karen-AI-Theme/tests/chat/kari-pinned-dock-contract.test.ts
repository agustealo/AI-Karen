import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = (path: string) =>
  readFileSync(resolve(process.cwd(), path), "utf8");

const dock = source("src/components/chat/copilotkit/KarenCopilotPinnedDock.tsx");
const shell = source("src/components/chat/copilotkit/KarenCopilotChat.tsx");
const css = source("src/app/kari-os.css");

describe("Kari OS stationary pinned workspace safety contract", () => {
  it("mounts exactly one dock beside the canonical verified response rail", () => {
    expect(shell.match(/<KarenCopilotVerifiedRail \/>/g)).toHaveLength(1);
    expect(shell.match(/<KarenCopilotPinnedDock \/>/g)).toHaveLength(1);
    expect(shell.indexOf("<KarenCopilotPinnedDock />")).toBeGreaterThan(
      shell.indexOf("<KarenCopilotVerifiedRail />"),
    );
  });

  it("keeps the approved 276px width and 1600px desktop-only layout", () => {
    expect(css).toContain("--kari-dock-width: 276px");
    expect(css).toContain("@media (min-width: 1600px)");
    expect(css).toContain("[data-kari-root] .karen-pinned-dock");
    expect(css).toContain("overflow-y: auto");
    expect(dock).toContain('aria-label="Pinned workspace"');
  });

  it("displays only canonical validated read-only references, never reconstructed cards", () => {
    expect(dock).toContain("parseAuthorizedPinReadback");
    expect(dock).toContain('apiClient.get<unknown>("/api/chat/ag-ui/pins")');
    expect(dock).toContain("Secure pinning not yet available");
    expect(dock).toContain("Full cards cannot be restored");
    expect(dock).not.toMatch(/localStorage\\.|sessionStorage\\.|setItem\\(/);
    expect(dock).not.toMatch(/\\bonClick=|\\bonSubmit=|apiClient\\.post\\(|apiClient\\.put\\(/);
    expect(dock).not.toContain("KarenPresentationRegistry");
    expect(dock).toContain('data-testid="karen-pinning-not-available"');
    expect(dock).toContain('data-testid="karen-pins-authorized"');
  });
});
