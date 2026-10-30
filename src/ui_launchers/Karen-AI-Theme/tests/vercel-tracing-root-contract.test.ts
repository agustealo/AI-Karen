import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The Next.js app is deployed as a Vercel project rooted at this package.
 * A wider output tracing root is retained only for local/Docker builds.
 * Neither runtime path may point to a missing or inferred Next module.
 */
describe("Vercel Next.js output tracing contract", () => {
  it("traces the Vercel server from the frontend package, not its parent src tree", () => {
    const config = readFileSync(join(process.cwd(), "next.config.ts"), "utf8");
    expect(config).toMatch(/outputFileTracingRoot:\s*process\.env\.VERCEL\s*===\s*'1'/);
    expect(config).toMatch(/\?\s*__dirname\s*:\s*path\.resolve\(__dirname, '\.\.\/\.\.'\)/);
  });

  it("keeps build-time Next.js runtime as a real pinned application dependency", () => {
    const pkg = JSON.parse(
      readFileSync(join(process.cwd(), "package.json"), "utf8"),
    ) as { dependencies?: Record<string, string> };
    expect(pkg.dependencies?.next).toMatch(/^\d+\.\d+\.\d+$/);
    expect(pkg.dependencies?.react).toBeDefined();
  });
});
