"use client";

/** Compatibility adapter for the retiring assistant-ui chat only. */
import { useAui } from "@assistant-ui/react";
import { KarenBrowserDictationCapture } from "../voice/KarenBrowserDictationCapture";
export { KarenBrowserDictationCapture } from "../voice/KarenBrowserDictationCapture";
export { mergeDictatedText } from "../KarenVoiceDraftPort";

export function KarenBrowserDictation() {
  const aui = useAui();
  return <KarenBrowserDictationCapture port={{
    readText: () => aui.composer().getState().text || "",
    writeText: (text) => aui.composer().setText(text),
  }} />;
}
