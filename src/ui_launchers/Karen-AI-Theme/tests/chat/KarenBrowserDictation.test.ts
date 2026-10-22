import { describe, expect, it } from "vitest";
import { mergeDictatedText } from "@/components/chat/assistant-ui/KarenBrowserDictation";

describe("browser dictation draft preservation", () => {
  it("preserves existing text and appends recognized speech", () => {
    expect(mergeDictatedText("Keep this draft", " add these words ")).toBe("Keep this draft add these words");
  });

  it("leaves a draft unchanged for empty transcripts", () => {
    expect(mergeDictatedText("Do not erase", "   ")).toBe("Do not erase");
  });

  it("uses recognized text for an empty draft", () => {
    expect(mergeDictatedText("", "Hello Karen")).toBe("Hello Karen");
  });
});
