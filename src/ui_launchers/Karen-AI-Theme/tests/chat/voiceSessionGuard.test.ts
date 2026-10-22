import { describe, expect, it } from "vitest";
import { isCurrentVoiceSession } from "@/components/chat/assistant-ui/voiceSessionGuard";

describe("voice generation guard", () => {
  it("accepts only the mounted active recording", () => {
    expect(isCurrentVoiceSession(true, 5, 5)).toBe(true);
    expect(isCurrentVoiceSession(true, 6, 5)).toBe(false);
    expect(isCurrentVoiceSession(false, 5, 5)).toBe(false);
  });
});
