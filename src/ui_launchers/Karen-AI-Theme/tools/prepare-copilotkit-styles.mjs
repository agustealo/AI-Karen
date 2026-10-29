import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * CopilotKit v2 ships browser-ready Tailwind v4 CSS. Karen's existing
 * Tailwind v3 PostCSS pipeline cannot reprocess its vendor @layer rules.
 *
 * Copy only the installed locked-package asset to a generated static URL.
 * No CDN, checked-in vendor fork or new CSS compiler. Fail on missing
 * or unexpectedly tiny asset instead of rendering an unstyled preview.
 */
const output = join(import.meta.dirname, "..", "public", "vendor", "copilotkit-v2.css");
let source;
try {
  source = fileURLToPath(import.meta.resolve("@copilotkit/react-core/v2/styles.css"));
} catch {
  throw new Error("CopilotKit v2 stylesheet is not available in the installed package");
}
if (!source.endsWith(".css") || !source.includes("copilotkit")) {
  throw new Error("Resolved CopilotKit stylesheet is not an approved local CSS asset");
}
const css = await readFile(source, "utf8");
if (css.length < 10000 || !css.includes("@layer")) {
  throw new Error("CopilotKit stylesheet content is unexpectedly missing or invalid");
}
await mkdir(dirname(output), { recursive: true });
await writeFile(output, css, { encoding: "utf8", mode: 0o644 });
