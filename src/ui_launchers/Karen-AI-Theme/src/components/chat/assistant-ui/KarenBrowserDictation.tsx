"use client";

import { useAui } from "@assistant-ui/react";
import { KarenBrowserDictationCapture } from "../KarenBrowserDictationCapture";
export { KarenBrowserDictationCapture } from "../KarenBrowserDictationCapture";
export { mergeDictatedText } from "../KarenVoiceDraftPort";

/** Assistant-ui-only adapter. Consent and recognition belong to shared capture. */
export function KarenBrowserDictation() {
  const aui = useAui();
  return <KarenBrowserDictationCapture port={{
    readText: () => aui.composer().getState().text || "",
    writeText: (text) => aui.composer().setText(text),
  }} />;
}
