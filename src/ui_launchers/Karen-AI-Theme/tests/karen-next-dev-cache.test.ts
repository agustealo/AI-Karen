import {
  existsSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { afterEach, describe, expect, it } from "vitest";

const ROOT = process.cwd();
const SCRIPT = path.join(ROOT, "tools/prepare-next-dev-cache.mjs");
const INPUTS = [
  "package.json",
  "package-lock.json",
  "next.config.ts",
  "tailwind.config.ts",
  "tools/prepare-copilotkit-styles.mjs",
] as const;
const disposableRoots: string[] = [];

function fixture() {
  const root = mkdtempSync(path.join(tmpdir(), "karen-next-dev-cache-"));
  disposableRoots.push(root);
  for (const name of INPUTS) {
    const pathname = path.join(root, name);
    mkdirSync(path.dirname(pathname), { recursive: true });
    writeFileSync(pathname, readFileSync(path.join(ROOT, name)));
  }
  return root;
}

function prepare(root: string) {
  return spawnSync(process.execPath, [SCRIPT], {
    cwd: root,
    encoding: "utf8",
    timeout: 15000,
  });
}

afterEach(() => {
  for (const root of disposableRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("Next.js dev cache integrity", () => {
  it("clears stale compiled assets at first startup but keeps the Docker volume directory", () => {
    const root = fixture();
    const cache = path.join(root, ".next");
    mkdirSync(path.join(cache, "static", "chunks"), { recursive: true });
    writeFileSync(path.join(cache, "static", "chunks", "stale-copilotkit-web-inspector.js"), "old");
    const before = lstatSync(cache);
    const result = prepare(root);
    expect(result.status, result.stderr).toBe(0);
    expect(existsSync(path.join(cache, "static"))).toBe(false);
    expect(lstatSync(cache).ino).toBe(before.ino);
    expect(readFileSync(path.join(cache, ".karen-dev-cache-fingerprint"), "utf8"))
      .toMatch(/^[0-9a-f]{64}\n$/);
  });

  it("keeps reusable dev chunks on unchanged restart and invalidates on dependency changes", () => {
    const root = fixture();
    const cache = path.join(root, ".next");
    expect(prepare(root).status).toBe(0);
    const marker = path.join(cache, ".karen-dev-cache-fingerprint");
    const prior = readFileSync(marker, "utf8");
    const active = path.join(cache, "active-webpack-chunk.js");
    writeFileSync(active, "current");
    expect(prepare(root).status).toBe(0);
    expect(readFileSync(active, "utf8")).toBe("current");

    const lock = path.join(root, "package-lock.json");
    writeFileSync(lock, readFileSync(lock, "utf8") + "\n");
    const changed = prepare(root);
    expect(changed.status, changed.stderr).toBe(0);
    expect(existsSync(active)).toBe(false);
    expect(readFileSync(marker, "utf8")).not.toBe(prior);
  });

  it("removes production-build artifacts before entering the development compiler", () => {
    const root = fixture();
    const cache = path.join(root, ".next");
    expect(prepare(root).status).toBe(0);
    writeFileSync(path.join(cache, "BUILD_ID"), "production-build");
    writeFileSync(path.join(cache, "production-chunk.js"), "production");
    const result = prepare(root);
    expect(result.status, result.stderr).toBe(0);
    expect(existsSync(path.join(cache, "BUILD_ID"))).toBe(false);
    expect(existsSync(path.join(cache, "production-chunk.js"))).toBe(false);
    expect(existsSync(path.join(cache, ".karen-dev-cache-fingerprint"))).toBe(true);
  });

  it.skipIf(process.platform === "win32")(
    "refuses a symlinked cache directory rather than deleting another directory",
    () => {
      const root = fixture();
      const external = mkdtempSync(path.join(tmpdir(), "karen-next-outside-"));
      disposableRoots.push(external);
      writeFileSync(path.join(external, "keep.txt"), "private");
      symlinkSync(external, path.join(root, ".next"), "dir");
      const result = prepare(root);
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain("Refusing to use a non-directory or linked Next.js cache");
      expect(readFileSync(path.join(external, "keep.txt"), "utf8")).toBe("private");
    },
  );

  it.skipIf(process.platform === "win32")(
    "rejects a linked marker without reading or deleting outside its cache root",
    () => {
      const root = fixture();
      const cache = path.join(root, ".next");
      const external = path.join(root, "outside.txt");
      mkdirSync(cache);
      writeFileSync(external, "private");
      symlinkSync(external, path.join(cache, ".karen-dev-cache-fingerprint"));
      const result = prepare(root);
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain("Refusing to read a non-regular Next.js cache marker");
      expect(readFileSync(external, "utf8")).toBe("private");
    },
  );

  it.skipIf(process.platform === "win32")(
    "unlinks a nested symlink during invalidation without following its target",
    () => {
      const root = fixture();
      const cache = path.join(root, ".next");
      const external = path.join(root, "outside");
      mkdirSync(cache);
      mkdirSync(external);
      writeFileSync(path.join(external, "keep.txt"), "private");
      symlinkSync(external, path.join(cache, "old-chunks"), "dir");
      const result = prepare(root);
      expect(result.status, result.stderr).toBe(0);
      expect(existsSync(path.join(cache, "old-chunks"))).toBe(false);
      expect(readFileSync(path.join(external, "keep.txt"), "utf8")).toBe("private");
    },
  );

  it("runs only before the dev server, never as a production build step", () => {
    const scripts = JSON.parse(
      readFileSync(path.join(ROOT, "package.json"), "utf8"),
    ).scripts as { dev: string; build: string };
    const script = "node tools/prepare-next-dev-cache.mjs";
    expect(scripts.dev.startsWith(script + " &&")).toBe(true);
    expect(scripts.build).not.toContain(script);
  });
});
