import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import { createRequire } from "node:module";

/**
 * Copy the stylesheet actually exported by the pinned CopilotKit package.
 * Resolving the CSS subpath with import.meta.resolve is not portable across
 * installed-package/export layouts. Read the installed manifest instead.
 *
 * Keep vendor Tailwind v4 CSS out of Karen's Tailwind v3 PostCSS pipeline.
 * Missing or invalid dependencies remain a hard startup error.
 */
const require = createRequire(import.meta.url);
const output = join(import.meta.dirname, "..", "public", "vendor", "copilotkit-v2.css");

let manifestPath;
try {
  manifestPath = require.resolve("@copilotkit/react-core/package.json");
} catch {
  throw new Error(
    "CopilotKit react-core is not installed. Reinstall dependencies from package-lock.json before starting the web server.",
  );
}

const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const version = manifest.version;
if (version !== "1.79.1") {
  throw new Error(`CopilotKit react-core version mismatch: expected 1.79.1, found ${version}`);
}

const exportedAsset = manifest.exports?.["./v2/styles.css"];
const relativeAsset = typeof exportedAsset === "string"
  ? exportedAsset
  : exportedAsset?.default ?? exportedAsset?.import;

if (typeof relativeAsset !== "string" || !relativeAsset.startsWith("./")) {
  throw new Error("Installed CopilotKit package does not export the v2 stylesheet");
}

const packageRoot = dirname(manifestPath);
const source = resolve(packageRoot, relativeAsset);
if (!source.startsWith(packageRoot + sep) || !source.endsWith(".css") || isAbsolute(relativeAsset)) {
  throw new Error("CopilotKit v2 stylesheet export escapes the installed package");
}

let css;
try {
  css = await readFile(source, "utf8");
} catch {
  throw new Error(
    "CopilotKit v2 stylesheet is missing from the installed package. Reinstall the locked dependencies.",
  );
}
if (css.length < 10000 || !css.includes("@layer")) {
  throw new Error("CopilotKit stylesheet content is unexpectedly missing or invalid");
}

await mkdir(dirname(output), { recursive: true });
await writeFile(output, css, { encoding: "utf8", mode: 0o644 });
