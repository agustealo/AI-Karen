import { describe, expect, it } from "vitest";
import { canCommitVoiceResult, isCurrentVoiceSession } from "@/components/chat/assistant-ui/voiceSessionGuard";

describe("voice generation guard", () => {
  it("accepts only the mounted active recording", () => {
    expect(isCurrentVoiceSession(true, 5, 5)).toBe(true);
    expect(isCurrentVoiceSession(true, 6, 5)).toBe(false);
    expect(isCurrentVoiceSession(false, 5, 5)).toBe(false);
  });
});

describe("voice upload cancellation", () => {
  it("prevents canceled or stale operations from uploading or changing drafts", () => {
    expect(canCommitVoiceResult(true, 4, 4, false)).toBe(true);
    expect(canCommitVoiceResult(true, 4, 4, true)).toBe(false);
    expect(canCommitVoiceResult(true, 5, 4, false)).toBe(false);
    expect(canCommitVoiceResult(false, 4, 4, false)).toBe(false);
  });
});

describe("late recorder error ownership", () => {
  it("rejects error callbacks from a discarded or replaced session", () => {
    const discardedGeneration = 3;
    const activeGeneration = 4;
    expect(isCurrentVoiceSession(true, activeGeneration, discardedGeneration)).toBe(false);
    expect(isCurrentVoiceSession(false, discardedGeneration, discardedGeneration)).toBe(false);
    expect(isCurrentVoiceSession(true, activeGeneration, activeGeneration)).toBe(true);
  });
});
