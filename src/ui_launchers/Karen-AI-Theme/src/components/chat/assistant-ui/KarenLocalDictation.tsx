"use client";

import { useAui } from "@assistant-ui/react";
import { KarenLocalDictationCapture } from "../KarenLocalDictationCapture";
export { KarenLocalDictationCapture } from "../KarenLocalDictationCapture";

/** Assistant-ui-only adapter. Shared microphone capture owns transcription. */
export function KarenLocalDictation() {
  const aui = useAui();
  return <KarenLocalDictationCapture port={{
    readText: () => aui.composer().getState().text || "",
    writeText: (text) => aui.composer().setText(text),
  }} />;
}
