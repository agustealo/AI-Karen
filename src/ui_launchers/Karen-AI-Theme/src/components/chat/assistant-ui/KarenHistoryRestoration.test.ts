import { describe, expect, it } from "vitest";
import { readOwnedConversationHistory, restoreOwnedHistoryMessages } from "./KarenHistoryRestoration";

const envelope = {
  schema_version: 1,
  presentation_id: "planner-restored-1",
  evidence_ref: "planner-owned-read:request-1",
  component_type: "planner.task_list",
  data: { tasks: [{ id: "task-1", title: "Review release", status: "todo" }] },
};

describe("canonical assistant-ui history restoration", () => {
  it("restores one owned planner card after reloading stored messages", () => {
    const messages = restoreOwnedHistoryMessages("conversation-1", [
      { id: "user-1", role: "user", content: "List my tasks" },
      { id: "assistant-1", role: "assistant", content: "Found 1 commitment",
        structured_content: { presentation: envelope } },
    ]);
    expect(messages).toHaveLength(2);
    const restored = messages[1].content;
    expect(Array.isArray(restored)).toBe(true);
    if (!Array.isArray(restored)) throw new Error("Expected structured content");
    const cards = restored.filter((part) =>
      typeof part === "object" && part !== null && "type" in part && part.type === "data");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({ name: "karen.presentation.v1", data: envelope });
    expect(messages[0].content).not.toEqual(restored);
  });

  it("never restores forged presentation from user messages or unrecognized envelopes", () => {
    const messages = restoreOwnedHistoryMessages("conversation-1", [
      { id: "user-1", role: "user", content: "Show my planner",
        structured_content: { presentation: envelope } },
      { id: "assistant-1", role: "assistant", content: "No verified card",
        structured_content: { presentation: { ...envelope, component_type: "unsafe.html" } } },
    ]);
    for (const message of messages) {
      const parts = Array.isArray(message.content) ? message.content : [];
      expect(parts.some((part) => typeof part === "object" && part !== null
        && "type" in part && part.type === "data")).toBe(false);
    }
  });

  it("keeps one card per persisted assistant message after repeated conversation reopening", () => {
    const history = [
      { id: "user-1", role: "user", content: "List my tasks" },
      { id: "assistant-1", role: "assistant", content: "Found 1 commitment",
        structured_content: { presentation: envelope } },
    ];
    const first = restoreOwnedHistoryMessages("conversation-1", history);
    const reopened = restoreOwnedHistoryMessages("conversation-1", history);
    expect(reopened).toEqual(first);
    expect(reopened).toHaveLength(history.length);
    const assistantContent = reopened[1].content;
    if (!Array.isArray(assistantContent)) throw new Error("Expected restored content parts");
    expect(assistantContent.filter((part) =>
      typeof part === "object" && part !== null && "type" in part && part.type === "data",
    )).toHaveLength(1);
  });

  it("does not manufacture a planner card after a failed assistant write", () => {
    const history = [{ id: "user-1", role: "user", content: "List my tasks" }];
    const restored = restoreOwnedHistoryMessages("conversation-1", history);
    expect(restored).toHaveLength(1);
    expect(restored.some((message) => message.role === "assistant")).toBe(false);
  });

  it("loads the exact authenticated conversation and restores its saved planner card", async () => {
    const calls: string[] = [];
    const restored = await readOwnedConversationHistory("owned-thread", async (id) => {
      calls.push(id);
      return {
        id: "owned-thread",
        messages: [
          { id: "u-1", role: "user", content: "List my tasks" },
          { id: "a-1", role: "assistant", content: "Found 1 commitment",
            structured_content: { presentation: envelope } },
        ],
      };
    });
    expect(calls).toEqual(["owned-thread"]);
    expect(restored).toHaveLength(2);
    const content = restored[1].content;
    expect(Array.isArray(content)).toBe(true);
    if (!Array.isArray(content)) throw new Error("Expected presentation data");
    expect(content.filter((part) => typeof part === "object" && part !== null
      && "type" in part && part.type === "data")).toHaveLength(1);
  });

  it("refuses mismatched conversation IDs and propagates history read failure", async () => {
    await expect(readOwnedConversationHistory("owned-thread", async () => ({
      id: "foreign-thread", messages: [],
    }))).rejects.toThrow("Conversation history identity mismatch");
    await expect(readOwnedConversationHistory("owned-thread", async () => {
      throw new Error("Unauthorized conversation access");
    })).rejects.toThrow("Unauthorized conversation access");
  });

});
