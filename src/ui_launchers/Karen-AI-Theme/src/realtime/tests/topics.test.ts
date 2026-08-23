import { describe, it, expect } from "vitest";
import {
  userTopic,
  conversationTopic,
  tenantNotificationsTopic,
  resolveTopic,
  TopicRegistry,
} from "../topics";

describe("topics", () => {
  const tenantId = "00000000-0000-0000-0000-000000000001";

  it("generates user topic", () => {
    expect(userTopic(tenantId, "00000000-0000-0000-0000-000000000011")).toBe(
      "tenant:00000000-0000-0000-0000-000000000001:user:00000000-0000-0000-0000-000000000011"
    );
  });

  it("generates conversation topic", () => {
    expect(conversationTopic(tenantId, "00000000-0000-0000-0000-000000000012")).toBe(
      "tenant:00000000-0000-0000-0000-000000000001:conversation:00000000-0000-0000-0000-000000000012"
    );
  });

  it("generates notifications topic", () => {
    expect(tenantNotificationsTopic(tenantId)).toBe(
      "tenant:00000000-0000-0000-0000-000000000001:notifications"
    );
  });

  it("resolves valid topic", () => {
    const topic = conversationTopic(tenantId, "00000000-0000-0000-0000-000000000012");
    expect(resolveTopic(topic)).toBe(topic);
  });

  it("resolves valid notifications topic", () => {
    expect(resolveTopic("tenant:00000000-0000-0000-0000-000000000001:notifications")).toBe(
      "tenant:00000000-0000-0000-0000-000000000001:notifications"
    );
  });

  it("rejects invalid topic", () => {
    expect(resolveTopic("bad")).toBeNull();
  });

  it("registry generates topics", () => {
    const registry = new TopicRegistry(tenantId);
    expect(registry.user("00000000-0000-0000-0000-000000000011")).toBe(
      userTopic(tenantId, "00000000-0000-0000-0000-000000000011")
    );
  });
});
