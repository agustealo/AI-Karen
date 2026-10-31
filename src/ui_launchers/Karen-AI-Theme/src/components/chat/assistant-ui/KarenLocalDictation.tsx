"use client";

/** Compatibility adapter for the retiring assistant-ui chat only. */
import { useAui } from "@assistant-ui/react";
import { KarenLocalDictationCapture } from "../voice/KarenLocalDictationCapture";
export { KarenLocalDictationCapture } from "../voice/KarenLocalDictationCapture";

export function KarenLocalDictation() {
  const aui = useAui();
  return <KarenLocalDictationCapture port={{
    readText: () => aui.composer().getState().text || "",
    writeText: (text) => aui.composer().setText(text),
  }} />;
}
