import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const source = readFileSync(
  fileURLToPath(new URL("./AgentsPage.tsx", import.meta.url)),
  "utf8",
);

describe("AgentsPage control-plane boundary", () => {
  it("fails closed before non-admin catalog access", () => {
    const nonAdminGuard = source.indexOf("if (!isAdmin) {");
    const catalogRequest = source.indexOf(
      'apiClient.get<AgentRecord[]>("/api/agents")',
    );

    expect(nonAdminGuard).toBeGreaterThan(-1);
    expect(catalogRequest).toBeGreaterThan(-1);
    expect(nonAdminGuard).toBeLessThan(catalogRequest);
  });

  it("does not load management inventory for ordinary users", () => {
    expect(source).toContain("if (isAuthenticated && isAdmin) {");
    expect(source).toContain("void loadToolInventory();");
  });

  it("presents the installation-wide registry as an admin control plane", () => {
    expect(source).toContain("Administrator Control Plane");
    expect(source).toContain("legacy agent registry is installation-wide");
    expect(source).not.toContain("Read-Only Access");
    expect(source).not.toContain("You can inspect the registered agents");
  });
});
