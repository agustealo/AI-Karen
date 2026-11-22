import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();
const WORKFLOW = path.resolve(
  ROOT,
  "../../../.github/workflows/web-pnpm-install-proof.yml",
);

describe("Repository-level plugin UI build contract", () => {
  it("routes pnpm CI through the canonical package build", () => {
    const scripts = JSON.parse(
      readFileSync(path.join(ROOT, "package.json"), "utf8"),
    ).scripts as { build: string };
    const workflow = readFileSync(WORKFLOW, "utf8");

    expect(scripts.build.startsWith(
      "node tools/sync-plugin-import-map.mjs && node --test ",
    )).toBe(true);
    expect(workflow).toMatch(/run: pnpm build/);
    expect(workflow).not.toMatch(/run: pnpm exec next build/);
  });
});
